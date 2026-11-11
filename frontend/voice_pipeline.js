var VoicePipeline = (function () {
  var TARGET_RATE = 16000;
  var VOICE_THRESHOLD = 0.025;
  var SILENCE_MS = 1100;
  var MIN_SPEECH_MS = 350;
  var MAX_SPEECH_MS = 20000;

  var onFinalText = null;
  var onState = null;
  var onInterim = null;

  var stream = null;
  var context = null;
  var processor = null;
  var inputRate = 48000;
  var wanted = false;
  var speaking = false;
  var speechStart = 0;
  var lastVoice = 0;
  var recorded = [];
  var preRoll = [];
  var player = null;
  var fallbackVoice = null;

  function supported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && (window.AudioContext || window.webkitAudioContext));
  }

  function resetCapture() {
    speaking = false;
    recorded = [];
    preRoll = [];
  }

  function downsample(chunks) {
    var total = 0;
    for (var i = 0; i < chunks.length; i++) {
      total = total + chunks[i].length;
    }
    var merged = new Float32Array(total);
    var offset = 0;
    for (var j = 0; j < chunks.length; j++) {
      merged.set(chunks[j], offset);
      offset = offset + chunks[j].length;
    }
    var ratio = inputRate / TARGET_RATE;
    var newLength = Math.floor(merged.length / ratio);
    var result = new Float32Array(newLength);
    for (var k = 0; k < newLength; k++) {
      var start = Math.floor(k * ratio);
      var end = Math.floor((k + 1) * ratio);
      var sum = 0;
      var count = 0;
      for (var m = start; m < end && m < merged.length; m++) {
        sum = sum + merged[m];
        count = count + 1;
      }
      result[k] = count > 0 ? sum / count : 0;
    }
    return result;
  }

  function encodeWav(samples) {
    var buffer = new ArrayBuffer(44 + samples.length * 2);
    var view = new DataView(buffer);
    function writeText(offset, text) {
      for (var i = 0; i < text.length; i++) {
        view.setUint8(offset + i, text.charCodeAt(i));
      }
    }
    writeText(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeText(8, "WAVE");
    writeText(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, TARGET_RATE, true);
    view.setUint32(28, TARGET_RATE * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeText(36, "data");
    view.setUint32(40, samples.length * 2, true);
    for (var i = 0; i < samples.length; i++) {
      var value = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true);
    }
    return buffer;
  }

  function sendAudio(chunks) {
    var wav = encodeWav(downsample(chunks));
    onState("transcribing");
    fetch("/api/stt", {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wav,
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        var text = result.ok && result.data.text ? result.data.text.trim() : "";
        if (text === "") {
          if (!result.ok) {
            onInterim("Could not hear that: " + (result.data.detail || "error"));
          }
          wanted = true;
          onState("listening");
          return;
        }
        onFinalText(text);
      })
      .catch(function () {
        wanted = true;
        onState("listening");
      });
  }

  function finishSpeech() {
    var chunks = recorded;
    var length = lastVoice - speechStart;
    resetCapture();
    wanted = false;
    if (length < MIN_SPEECH_MS) {
      wanted = true;
      return;
    }
    sendAudio(chunks);
  }

  function handleAudio(event) {
    if (!wanted) {
      return;
    }
    var input = event.inputBuffer.getChannelData(0);
    var copy = new Float32Array(input);
    var sum = 0;
    for (var i = 0; i < copy.length; i++) {
      sum = sum + copy[i] * copy[i];
    }
    var rms = Math.sqrt(sum / copy.length);
    var now = Date.now();
    if (rms > VOICE_THRESHOLD) {
      if (!speaking) {
        speaking = true;
        speechStart = now;
        recorded = preRoll.slice();
        onInterim("Hearing you...");
      }
      lastVoice = now;
    }
    if (speaking) {
      recorded.push(copy);
      if (now - lastVoice > SILENCE_MS || now - speechStart > MAX_SPEECH_MS) {
        finishSpeech();
      }
    } else {
      preRoll.push(copy);
      if (preRoll.length > 4) {
        preRoll.shift();
      }
    }
  }

  function ensureMic() {
    if (stream !== null) {
      return Promise.resolve();
    }
    return navigator.mediaDevices
      .getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } })
      .then(function (mediaStream) {
        stream = mediaStream;
        var AudioCtx = window.AudioContext || window.webkitAudioContext;
        context = new AudioCtx();
        inputRate = context.sampleRate;
        var source = context.createMediaStreamSource(stream);
        processor = context.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = handleAudio;
        source.connect(processor);
        processor.connect(context.destination);
      });
  }

  function startListening() {
    ensureMic()
      .then(function () {
        if (context.state === "suspended") {
          context.resume();
        }
        resetCapture();
        wanted = true;
        onState("listening");
      })
      .catch(function () {
        wanted = false;
        onState("mic-blocked");
      });
  }

  function stopListening() {
    wanted = false;
    resetCapture();
  }

  function browserSpeak(text, done) {
    if (!window.speechSynthesis) {
      done();
      return;
    }
    window.speechSynthesis.cancel();
    var utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-IN";
    var finished = false;
    function finish() {
      if (!finished) {
        finished = true;
        done();
      }
    }
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  }

  function speak(text, done) {
    stopSpeaking();
    var finished = false;
    function finish() {
      if (!finished) {
        finished = true;
        done();
      }
    }
    fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("tts failed");
        }
        return response.blob();
      })
      .then(function (blob) {
        player = new Audio(URL.createObjectURL(blob));
        player.onended = finish;
        player.onerror = function () {
          browserSpeak(text, finish);
        };
        return player.play();
      })
      .catch(function () {
        browserSpeak(text, finish);
      });
  }

  function stopSpeaking() {
    if (player !== null) {
      player.onended = null;
      player.onerror = null;
      player.pause();
      player = null;
    }
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
  }

  return {
    supported: supported,
    start: function (handlers) {
      onFinalText = handlers.onFinalText;
      onState = handlers.onState;
      onInterim = handlers.onInterim;
    },
    startListening: startListening,
    stopListening: stopListening,
    speak: speak,
    stopSpeaking: stopSpeaking,
  };
})();