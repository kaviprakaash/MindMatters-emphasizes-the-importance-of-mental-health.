(function () {
    const NICK_RANDOM = 'campus_random_nick';
    const NICK_LOUNGE = 'campus_lounge_nick';

    function escapeHtml(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function formatTime(ts) {
        const d = new Date(Number(ts) * 1000);
        return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    }

    // —— Tabs ——
    const tabRandom = document.getElementById('tab-random');
    const tabLounge = document.getElementById('tab-lounge');
    const panelRandom = document.getElementById('panel-random');
    const panelLounge = document.getElementById('panel-lounge');

    let loungePoll = null;
    let randomStatusPoll = null;
    let randomMsgPoll = null;
    let activeMode = 'random';

    function stopLoungePoll() {
        if (loungePoll) {
            clearInterval(loungePoll);
            loungePoll = null;
        }
    }

    function stopRandomPolls() {
        if (randomStatusPoll) {
            clearInterval(randomStatusPoll);
            randomStatusPoll = null;
        }
        if (randomMsgPoll) {
            clearInterval(randomMsgPoll);
            randomMsgPoll = null;
        }
    }

    function setTab(mode) {
        activeMode = mode;
        const isRand = mode === 'random';
        tabRandom.setAttribute('aria-selected', isRand);
        tabLounge.setAttribute('aria-selected', !isRand);
        tabRandom.className = isRand
            ? 'py-2.5 px-4 sm:px-5 text-sm font-semibold rounded-lg transition-colors bg-[#1D3557] text-white whitespace-nowrap'
            : 'py-2.5 px-4 sm:px-5 text-sm font-semibold rounded-lg transition-colors text-[#1D3557] hover:bg-gray-50 whitespace-nowrap';
        tabLounge.className = !isRand
            ? 'py-2.5 px-4 sm:px-5 text-sm font-semibold rounded-lg transition-colors bg-[#1D3557] text-white whitespace-nowrap'
            : 'py-2.5 px-4 sm:px-5 text-sm font-semibold rounded-lg transition-colors text-[#1D3557] hover:bg-gray-50 whitespace-nowrap';
        panelRandom.classList.toggle('hidden', !isRand);
        panelLounge.classList.toggle('hidden', isRand);
        panelLounge.hidden = isRand;
        if (isRand) {
            stopLoungePoll();
            if (pairId) {
                if (randomMsgPoll) clearInterval(randomMsgPoll);
                randomMsgPoll = setInterval(loadRandomMessages, 2500);
                loadRandomMessages();
            } else {
                fetch('/api/random_match/status')
                    .then((r) => r.json())
                    .then((d) => {
                        if (d.status === 'waiting' && !randomStatusPoll) {
                            randomStatus.textContent = 'Looking for someone else online…';
                            randomLeave.classList.remove('hidden');
                            randomStart.classList.add('hidden');
                            randomStatusPoll = setInterval(pollRandomStatus, 2000);
                        }
                    })
                    .catch(() => {});
            }
        } else {
            stopRandomPolls();
            startLounge();
        }
    }

    tabRandom.addEventListener('click', () => setTab('random'));
    tabLounge.addEventListener('click', () => setTab('lounge'));

    // —— Random 1-on-1 ——
    const randomNick = document.getElementById('random-nick');
    const randomStart = document.getElementById('random-start');
    const randomLeave = document.getElementById('random-leave');
    const randomStatus = document.getElementById('random-status');
    const randomWrap = document.getElementById('random-chat-wrap');
    const randomList = document.getElementById('random-messages');
    const randomInput = document.getElementById('random-input');
    const randomSend = document.getElementById('random-send');
    const randomErr = document.getElementById('random-error');

    let pairId = null;

    function showRandomErr(msg) {
        if (!msg) {
            randomErr.classList.add('hidden');
            randomErr.textContent = '';
            return;
        }
        randomErr.textContent = msg;
        randomErr.classList.remove('hidden');
    }

    if (localStorage.getItem(NICK_RANDOM) && randomNick) {
        randomNick.value = localStorage.getItem(NICK_RANDOM);
    }

    function renderRandomMessages(msgs) {
        if (!msgs || !msgs.length) {
            randomList.innerHTML =
                '<p class="text-xs text-gray-500 text-center py-6">Say hi — you’re in a private chat with one person.</p>';
            return;
        }
        randomList.innerHTML = msgs
            .map((m) => {
                const side = m.from_self ? 'ml-auto bg-indigo-100 border-indigo-200' : 'mr-auto bg-white border-gray-200';
                return `<div class="max-w-[85%] rounded-lg px-3 py-2 border text-sm shadow-sm ${side}">
                    <p class="text-gray-800 whitespace-pre-wrap break-words">${escapeHtml(m.body)}</p>
                    <p class="text-[10px] text-gray-400 mt-1">${escapeHtml(formatTime(m.created_at))}</p>
                </div>`;
            })
            .join('');
        randomList.scrollTop = randomList.scrollHeight;
    }

    async function loadRandomMessages() {
        if (!pairId) return;
        try {
            const res = await fetch(`/api/random_match/messages?pair_id=${encodeURIComponent(pairId)}`);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return;
            renderRandomMessages(data.messages || []);
        } catch (e) {
            console.error(e);
        }
    }

    function applyMatched(pid, partnerNick) {
        pairId = pid;
        randomStatus.textContent = `Connected with “${partnerNick}”. Only the two of you see this chat.`;
        randomWrap.classList.remove('hidden');
        randomLeave.classList.remove('hidden');
        randomStart.classList.add('hidden');
        showRandomErr('');
        loadRandomMessages();
        if (randomMsgPoll) clearInterval(randomMsgPoll);
        randomMsgPoll = setInterval(loadRandomMessages, 2500);
    }

    function applyIdle() {
        pairId = null;
        randomStatus.textContent = 'Idle — tap “Find someone” to join the queue.';
        randomWrap.classList.add('hidden');
        randomLeave.classList.add('hidden');
        randomStart.classList.remove('hidden');
        if (randomMsgPoll) {
            clearInterval(randomMsgPoll);
            randomMsgPoll = null;
        }
    }

    async function pollRandomStatus() {
        try {
            const res = await fetch('/api/random_match/status');
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return;
            if (data.status === 'matched' && data.pair_id) {
                applyMatched(data.pair_id, data.partner_nickname || 'Stranger');
                if (randomStatusPoll) {
                    clearInterval(randomStatusPoll);
                    randomStatusPoll = null;
                }
            } else if (data.status === 'waiting') {
                randomStatus.textContent = 'Looking for someone else online…';
                randomLeave.classList.remove('hidden');
                randomStart.classList.add('hidden');
            } else {
                applyIdle();
            }
        } catch (e) {
            console.error(e);
        }
    }

    randomStart.addEventListener('click', async () => {
        showRandomErr('');
        const nickname = (randomNick && randomNick.value.trim()) || 'Anonymous';
        localStorage.setItem(NICK_RANDOM, nickname);
        randomStart.disabled = true;
        try {
            const res = await fetch('/api/random_match/join', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nickname }),
            });
            const data = await res.json().catch(() => ({}));
            if (data.status === 'matched' && data.pair_id) {
                applyMatched(data.pair_id, data.partner_nickname || 'Stranger');
            } else if (data.status === 'waiting') {
                randomStatus.textContent = 'Looking for someone else online…';
                randomLeave.classList.remove('hidden');
                randomStart.classList.add('hidden');
                if (randomStatusPoll) clearInterval(randomStatusPoll);
                randomStatusPoll = setInterval(pollRandomStatus, 2000);
            } else {
                showRandomErr(data.error || 'Could not join');
            }
        } catch (e) {
            showRandomErr('Network error');
        } finally {
            randomStart.disabled = false;
        }
    });

    randomLeave.addEventListener('click', async () => {
        await fetch('/api/random_match/leave', { method: 'POST' });
        if (randomStatusPoll) {
            clearInterval(randomStatusPoll);
            randomStatusPoll = null;
        }
        applyIdle();
        showRandomErr('');
    });

    randomSend.addEventListener('click', async () => {
        showRandomErr('');
        const body = (randomInput && randomInput.value.trim()) || '';
        if (!body || !pairId) return;
        randomSend.disabled = true;
        try {
            const res = await fetch('/api/random_match/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pair_id: pairId, body }),
            });
            const data = await res.json().catch(() => ({}));
            if (res.status === 422 && data.message) {
                showRandomErr(data.message);
                return;
            }
            if (!res.ok) {
                showRandomErr(data.error || 'Send failed');
                return;
            }
            if (randomInput) randomInput.value = '';
            await loadRandomMessages();
        } catch (e) {
            showRandomErr('Network error');
        } finally {
            randomSend.disabled = false;
        }
    });

    if (randomInput) {
        randomInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                randomSend.click();
            }
        });
    }

    // On load: sync UI if already matched or waiting
    (async () => {
        try {
            const res = await fetch('/api/random_match/status');
            const data = await res.json().catch(() => ({}));
            if (data.status === 'matched' && data.pair_id) {
                applyMatched(data.pair_id, data.partner_nickname || 'Stranger');
            } else if (data.status === 'waiting') {
                randomStatus.textContent = 'Looking for someone else online…';
                randomLeave.classList.remove('hidden');
                randomStart.classList.add('hidden');
                if (randomStatusPoll) clearInterval(randomStatusPoll);
                randomStatusPoll = setInterval(pollRandomStatus, 2000);
            }
        } catch (e) {
            /* ignore */
        }
    })();

    // —— Whole campus lounge ——
    const loungeNick = document.getElementById('lounge-nick');
    const loungeList = document.getElementById('lounge-messages');
    const loungeInput = document.getElementById('lounge-input');
    const loungeSend = document.getElementById('lounge-send');
    const loungeStatus = document.getElementById('lounge-status');
    const loungeErr = document.getElementById('lounge-error');

    if (localStorage.getItem(NICK_LOUNGE) && loungeNick) {
        loungeNick.value = localStorage.getItem(NICK_LOUNGE);
    }

    function showLoungeErr(msg) {
        if (!msg) {
            loungeErr.classList.add('hidden');
            loungeErr.textContent = '';
            return;
        }
        loungeErr.textContent = msg;
        loungeErr.classList.remove('hidden');
    }

    function renderLoungeMessages(messages) {
        if (!messages.length) {
            loungeList.innerHTML =
                '<p class="text-sm text-gray-500 text-center py-8">No messages yet. Say hello to the campus.</p>';
            return;
        }
        loungeList.innerHTML = messages
            .map(
                (m) => `
            <div class="rounded-lg px-3 py-2 bg-white border border-gray-100 shadow-sm">
                <div class="flex justify-between gap-2 mb-1">
                    <span class="text-sm font-semibold text-[#1D3557]">${escapeHtml(m.nickname)}</span>
                    <span class="text-xs text-gray-400 shrink-0">${escapeHtml(formatTime(m.created_at))}</span>
                </div>
                <p class="text-sm text-gray-700 whitespace-pre-wrap break-words">${escapeHtml(m.body)}</p>
            </div>
        `
            )
            .join('');
        loungeList.scrollTop = loungeList.scrollHeight;
    }

    async function loadLounge() {
        try {
            const res = await fetch(
                `/api/campus_chat/messages?room=${encodeURIComponent('general')}`
            );
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                loungeStatus.textContent = 'Could not load';
                return;
            }
            loungeStatus.textContent = 'Connected';
            renderLoungeMessages(data.messages || []);
            showLoungeErr('');
        } catch (e) {
            loungeStatus.textContent = 'Offline';
            console.error(e);
        }
    }

    function startLounge() {
        loadLounge();
        stopLoungePoll();
        loungePoll = setInterval(loadLounge, 5000);
    }

    loungeSend.addEventListener('click', async () => {
        showLoungeErr('');
        const nickname = (loungeNick && loungeNick.value.trim()) || 'Anonymous';
        const body = (loungeInput && loungeInput.value.trim()) || '';
        if (!body) return;
        localStorage.setItem(NICK_LOUNGE, nickname);
        loungeSend.disabled = true;
        try {
            const res = await fetch('/api/campus_chat/post', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room_id: 'general', nickname, body }),
            });
            const data = await res.json().catch(() => ({}));
            if (res.status === 422 && data.message) {
                showLoungeErr(data.message);
                return;
            }
            if (!res.ok) {
                showLoungeErr(data.error || 'Could not send');
                return;
            }
            if (loungeInput) loungeInput.value = '';
            await loadLounge();
        } catch (e) {
            showLoungeErr('Network error');
        } finally {
            loungeSend.disabled = false;
        }
    });

    if (loungeInput) {
        loungeInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                loungeSend.click();
            }
        });
    }

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState !== 'visible') return;
        if (activeMode === 'lounge') loadLounge();
        if (activeMode === 'random' && pairId) loadRandomMessages();
    });
})();
