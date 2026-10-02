(function () {
    const root = document.getElementById("control");
    if (!root) return;

    const $ = (id) => document.getElementById(id);
    const pollMs = Number(root.dataset.pollMs) || 3000;
    const streamUrl = root.dataset.streamUrl;
    let sortie = root.dataset.sortie === "1";
    let lastEventId = Number(root.dataset.lastEventId) || 0;
    let pollTimer = null;
    let streamRetry = null;

    async function request(url, options) {
        const res = await fetch(url, Object.assign({ cache: "no-store" }, options));
        if (res.status === 401) {
            location.href = "/login";
            throw new Error("unauthorized");
        }
        return res.json();
    }

    let toastTimer = null;
    function toast(message) {
        const el = $("toast");
        el.textContent = message;
        el.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => (el.hidden = true), 3000);
    }

    function showLive(on) {
        $("home-view").hidden = on;
        $("live-view").hidden = !on;
        if (on) {
            startStream();
            poll();
            pollTimer = setInterval(poll, pollMs);
        } else {
            clearInterval(pollTimer);
            stopStream();
        }
    }

    function startStream() {
        const img = $("stream");
        img.onload = () => ($("stream-off").hidden = true);
        img.onerror = () => {
            $("stream-off").hidden = false;
            clearTimeout(streamRetry);
            streamRetry = setTimeout(startStream, 5000);
        };
        img.src = streamUrl + (streamUrl.includes("?") ? "&" : "?") + "t=" + Date.now();
    }

    function stopStream() {
        clearTimeout(streamRetry);
        $("stream").removeAttribute("src");
    }

    async function poll() {
        try {
            const data = await request("/api/live");
            $("poll-error").hidden = true;
            render(data);
        } catch (e) {
            if (e.message !== "unauthorized") $("poll-error").hidden = false;
        }
    }

    function render(d) {
        $("db-error").hidden = d.db_ok;
        $("v-online").innerHTML = d.online
            ? '<span class="dot on"></span>온라인'
            : '<span class="dot off"></span>오프라인' + (d.last_seen !== "-" ? ` <small class="muted">(${d.last_seen})</small>` : "");
        $("v-action").textContent = d.action_label;

        const level = $("v-level");
        level.className = "badge " + d.level;
        level.textContent = d.level_label;

        if (d.water_level === null || d.water_level === undefined) {
            $("v-water").textContent = "-";
            $("v-water-bar").style.width = "0";
        } else {
            const w = Math.max(0, Math.min(100, d.water_level));
            $("v-water").textContent = d.water_level.toFixed(1) + "%";
            $("v-water-bar").style.width = w + "%";
            $("v-water-bar").classList.toggle("low", w < 30);
        }

        const errors = $("v-errors");
        if (d.unresolved_errors.length) {
            errors.hidden = false;
            errors.textContent = "미해결 에러: " +
                d.unresolved_errors.map((e) => `[${e.code || "-"}] ${e.message || ""}`).join(", ");
        } else {
            errors.hidden = true;
        }
        $("v-lastlog").textContent = d.last_log ? `최근 로그: [${d.last_log.code || "-"}] ${d.last_log.message || ""}` : "";

        const ev = d.latest_event;
        const evLink = $("v-event");
        if (ev) {
            evLink.textContent = `#${ev.event_id} ${ev.status_label}`;
            evLink.href = ev.url;
            if (ev.event_id > lastEventId) {
                lastEventId = ev.event_id;
                showFireModal(ev);
            }
        }

        if (sortie && !d.sortie) {
            sortie = false;
            showLive(false);
            toast("RC카가 기지로 복귀했습니다.");
        }
    }

    function showFireModal(ev) {
        const temp = ev.temperature !== null ? ev.temperature.toFixed(1) + "℃" : "-";
        const score = ev.vision_score !== null ? (ev.vision_score * 100).toFixed(0) + "%" : "-";
        $("fire-modal-text").textContent =
            `${ev.detected_at} 화재가 감지되었습니다. (온도 ${temp}, 인식 신뢰도 ${score})`;
        $("fire-modal-link").href = ev.url;
        $("fire-modal").hidden = false;
    }
    $("fire-modal-close").addEventListener("click", () => ($("fire-modal").hidden = true));

    $("btn-sortie").addEventListener("click", async () => {
        try {
            const res = await request("/api/sortie", { method: "POST" });
            sortie = true;
            showLive(true);
            toast(res.message);
        } catch (e) {
            toast("출격 명령 전송 실패");
        }
    });

    document.querySelectorAll(".controls [data-cmd]").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const cmd = btn.dataset.cmd;
            if (cmd === "stop" && !confirm("RC카를 긴급 정지할까요?")) return;
            btn.disabled = true;
            try {
                const res = await request("/api/control/" + cmd, { method: "POST" });
                toast(res.message);
                poll();
            } catch (e) {
                toast("명령 전송 실패");
            } finally {
                btn.disabled = false;
            }
        });
    });

    if (sortie) showLive(true);
})();
