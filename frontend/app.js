var sessionId = null;
var callActive = false;
var busy = false;
var micPaused = false;

var statusEl = document.getElementById("status");
var orbEl = document.getElementById("orb");
var callBtn = document.getElementById("callBtn");
var micBtn = document.getElementById("micBtn");
var hintEl = document.getElementById("hint");
var transcriptEl = document.getElementById("transcript");
var typeForm = document.getElementById("typeForm");
var typeInput = document.getElementById("typeInput");
var actionsEl = document.getElementById("actions");
var sellerCard = document.getElementById("sellerCard");
var summaryCard = document.getElementById("summaryCard");
var summaryEl = document.getElementById("summary");

function setState(state) {
  var labels = { idle: "Idle", listening: "Listening", thinking: "Thinking", speaking: "Speaking" };
  statusEl.textContent = labels[state] || state;
  statusEl.className = "status " + state;
  orbEl.className = "orb " + state;
}

function addMessage(who, text) {
  var div = document.createElement("div");
  div.className = "msg " + who;
  var label = document.createElement("small");
  label.textContent = who === "bot" ? "Anaya (KAM)" : "You";
  var body = document.createElement("span");
  body.textContent = text;
  div.appendChild(label);
  div.appendChild(body);
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function percentText(lastValue, thisValue) {
  var change = ((thisValue - lastValue) / lastValue) * 100;
  var rounded = Math.round(change * 10) / 10;
  var cls = rounded < 0 ? "down" : "up";
  return '<span class="' + cls + '">' + (rounded > 0 ? "+" : "") + rounded + "%</span>";
}

function rupees(value) {
  return "Rs " + value.toLocaleString("en-IN");
}

function showSeller(seller) {
  var last = seller.last_month;
  var now = seller.this_month;
  var html = "<h3>" + seller.business + "</h3>";
  html += '<p class="muted">' + seller.name + " | " + seller.category + " | " + seller.city + "</p>";
  html += '<div class="kv"><span>Sales</span><span>' + rupees(last.sales) + " to " + rupees(now.sales) + " " + percentText(last.sales, now.sales) + "</span></div>";
  html += '<div class="kv"><span>Orders</span><span>' + last.orders + " to " + now.orders + " " + percentText(last.orders, now.orders) + "</span></div>";
  html += '<div class="kv"><span>Cancellation rate</span><span>' + last.cancellation_rate + "% to " + now.cancellation_rate + "%</span></div>";
  html += '<div class="kv"><span>Out-of-stock products</span><span>' + last.out_of_stock_products + " to " + now.out_of_stock_products + "</span></div>";
  html += '<div class="kv"><span>Avg selling price</span><span>' + rupees(last.avg_selling_price) + " to " + rupees(now.avg_selling_price) + "</span></div>";
  sellerCard.innerHTML = html;
}

function showActions(actions) {
  actionsEl.innerHTML = "";
  if (!actions || actions.length === 0) {
    actionsEl.innerHTML = '<li class="muted">Nothing yet.</li>';
    return;
  }
  for (var i = 0; i < actions.length; i++) {
    var li = document.createElement("li");
    li.textContent = actions[i].text;
    actionsEl.appendChild(li);
  }
}

function showSummary(summary) {
  if (!summary) {
    return;
  }
  summaryCard.hidden = false;
  summaryEl.innerHTML = "";
  var keys = Object.keys(summary);
  for (var i = 0; i < keys.length; i++) {
    var value = summary[keys[i]];
    var p = document.createElement("p");
    var title = keys[i].replace(/_/g, " ");
    var text = Array.isArray(value) ? value.join("; ") : String(value);
    p.innerHTML = "<b></b> ";
    p.firstChild.textContent = title + ":";
    p.appendChild(document.createTextNode(text));
    summaryEl.appendChild(p);
  }
}

function listenIfPossible() {
  if (!callActive || micPaused) {
    setState(callActive ? "idle" : "idle");
    return;
  }
  if (VoicePipeline.supported()) {
    VoicePipeline.startListening();
  }
}

function botSpeak(text) {
  setState("speaking");
  VoicePipeline.stopListening();
  VoicePipeline.speak(text, function () {
    if (callActive) {
      setState("listening");
      listenIfPossible();
    }
  });
}

function sendToServer(text) {
  if (busy || !callActive) {
    return;
  }
  busy = true;
  addMessage("user", text);
  setState("thinking");
  VoicePipeline.stopListening();
  fetch("/api/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, text: text }),
  })
    .then(function (response) {
      return response.json().then(function (data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function (result) {
      busy = false;
      if (!result.ok) {
        var message = result.data.detail || "Something went wrong.";
        addMessage("bot", message);
        botSpeak("Sorry ji, there was a problem. Please try again.");
        return;
      }
      var data = result.data;
      addMessage("bot", data.reply);
      showActions(data.actions);
      showSummary(data.summary);
      if (data.finished) {
        VoicePipeline.speak(data.reply, function () {
          endCall();
        });
        setState("speaking");
        return;
      }
      botSpeak(data.reply);
    })
    .catch(function () {
      busy = false;
      botSpeak("Sorry ji, I could not reach the server. Please try again.");
    });
}

function startCall() {
  callBtn.disabled = true;
  fetch("/api/session", { method: "POST" })
    .then(function (response) {
      return response.json();
    })
    .then(function (data) {
      sessionId = data.session_id;
      callActive = true;
      micPaused = false;
      transcriptEl.innerHTML = "";
      summaryCard.hidden = true;
      showActions([]);
      showSeller(data.seller);
      callBtn.textContent = "End call";
      callBtn.classList.add("live");
      callBtn.disabled = false;
      micBtn.disabled = false;
      micBtn.textContent = "Mute mic";
      addMessage("bot", data.greeting);
      botSpeak(data.greeting);
    })
    .catch(function () {
      callBtn.disabled = false;
      hintEl.textContent = "Could not start the call. Is the server running?";
    });
}

function endCall() {
  callActive = false;
  VoicePipeline.stopListening();
  VoicePipeline.stopSpeaking();
  callBtn.textContent = "Start call";
  callBtn.classList.remove("live");
  micBtn.disabled = true;
  setState("idle");
}

VoicePipeline.start({
  onFinalText: function (text) {
    if (text !== "") {
      sendToServer(text);
    }
  },
  onInterim: function (text) {
    hintEl.textContent = "Hearing: " + text;
  },
  onState: function (state) {
    if (state === "listening") {
      setState("listening");
      hintEl.textContent = "Listening... speak now, it sends when you pause.";
    }
    if (state === "transcribing") {
      setState("thinking");
      hintEl.textContent = "Understanding what you said...";
    }
    if (state === "mic-blocked") {
      hintEl.textContent = "Microphone is blocked. Allow it in the browser, or type below.";
      setState("idle");
    }
  },
});

callBtn.addEventListener("click", function () {
  if (callActive) {
    endCall();
  } else {
    startCall();
  }
});

micBtn.addEventListener("click", function () {
  micPaused = !micPaused;
  if (micPaused) {
    VoicePipeline.stopListening();
    micBtn.textContent = "Unmute mic";
    micBtn.classList.add("hot");
  } else {
    micBtn.textContent = "Mute mic";
    micBtn.classList.remove("hot");
    if (!busy) {
      listenIfPossible();
    }
  }
});

typeForm.addEventListener("submit", function (event) {
  event.preventDefault();
  var text = typeInput.value.trim();
  typeInput.value = "";
  if (text !== "") {
    sendToServer(text);
  }
});

if (!VoicePipeline.supported()) {
  hintEl.textContent = "Microphone not supported in this browser. You can still type below.";
}