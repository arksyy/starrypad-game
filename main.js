// StarryPad Simon Says – Web UI

const promptEl = document.getElementById("prompt");
const scoreLabel = document.getElementById("scoreLabel");
const gridEl = document.getElementById("grid");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const leaderList = document.getElementById("leaderList");
const nameModal = document.getElementById("nameModal");
const modalScore = document.getElementById("modalScore");
const nameInput = document.getElementById("nameInput");
const nameSubmit = document.getElementById("nameSubmit");

let ws = null;
let phase = "idle";
let pendingScore = 0;

// ── Helpers ──────────────────────────────────────────────

function setPrompt(text, action = false) {
  promptEl.textContent = text;
  promptEl.classList.toggle("action", action);
}

function setScore(n) {
  scoreLabel.textContent = String(n);
}

function getPad(idx) {
  return gridEl.querySelector(`[data-pad-index="${idx}"]`);
}

function lightPad(idx) {
  const el = getPad(idx);
  if (el) el.classList.add("active");
}

function unlightPad(idx) {
  const el = getPad(idx);
  if (el) el.classList.remove("active");
}

function flashPad(idx, className, ms = 250) {
  const el = getPad(idx);
  if (!el) return;
  el.classList.add(className);
  setTimeout(() => el.classList.remove(className), ms);
}

function updateButtons() {
  const connected = ws && ws.readyState === WebSocket.OPEN;
  startBtn.disabled = !connected || (phase !== "idle" && phase !== "gameover");
  stopBtn.disabled = !connected || phase === "idle" || phase === "gameover";
}

function renderLeaderboard(board) {
  leaderList.innerHTML = "";
  if (!board || board.length === 0) {
    leaderList.innerHTML = '<li class="empty">No scores yet</li>';
    return;
  }
  board.forEach((entry, i) => {
    const li = document.createElement("li");
    li.innerHTML =
      `<span class="rank">${i + 1}.</span>` +
      `<span class="name">${esc(entry.name)}</span>` +
      `<span class="lb-score">${entry.score}</span>`;
    leaderList.appendChild(li);
  });
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function showNameModal(score) {
  pendingScore = score;
  modalScore.textContent = String(score);
  nameInput.value = "";
  nameModal.classList.remove("hidden");
  nameInput.focus();
}

function hideNameModal() {
  nameModal.classList.add("hidden");
}

// ── Grid ─────────────────────────────────────────────────

function renderGrid() {
  gridEl.innerHTML = "";
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 4; col++) {
      const idx = (3 - row) * 4 + col;
      const cell = document.createElement("div");
      cell.className = "pad";
      cell.textContent = String(idx + 1);
      cell.dataset.padIndex = String(idx);
      gridEl.appendChild(cell);
    }
  }
}

// ── WebSocket ────────────────────────────────────────────

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => {
    phase = "idle";
    setPrompt("Press Start to play", true);
    setScore(0);
    updateButtons();
  };

  ws.onclose = () => {
    phase = "idle";
    setPrompt("Disconnected – reconnecting…");
    startBtn.disabled = true;
    stopBtn.disabled = true;
    setTimeout(connect, 2000);
  };

  ws.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }

    switch (data.type) {
      case "light":
        lightPad(data.pad);
        break;
      case "unlight":
        unlightPad(data.pad);
        break;
      case "score":
        setScore(data.score);
        break;
      case "phase":
        phase = data.phase;
        if (phase === "playing") setPrompt("Watch…");
        else if (phase === "input") setPrompt("Your turn", true);
        else if (phase === "idle") setPrompt("Press Start to play", true);
        updateButtons();
        break;
      case "gameover":
        phase = "gameover";
        setPrompt(`Game over!`, false);
        updateButtons();
        if (data.is_top5) {
          showNameModal(data.score);
        }
        break;
      case "correct":
        flashPad(data.pad, "good", 250);
        break;
      case "wrong":
        flashPad(data.pad, "bad", 600);
        break;
      case "leaderboard":
        renderLeaderboard(data.board);
        break;
      case "error":
        setPrompt(data.text);
        break;
    }
  };
}

// ── Button handlers ──────────────────────────────────────

startBtn.addEventListener("click", () => {
  send({ type: "start" });
});

stopBtn.addEventListener("click", () => {
  send({ type: "stop" });
});

nameSubmit.addEventListener("click", () => {
  const name = nameInput.value.trim();
  if (!name) return;
  send({ type: "submit_name", name, score: pendingScore });
  hideNameModal();
});

nameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") nameSubmit.click();
});

// ── Init ─────────────────────────────────────────────────

renderGrid();
connect();
