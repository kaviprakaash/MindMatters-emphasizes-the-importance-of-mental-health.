(function () {
    const startBtn = document.getElementById('start-timer');
    const stopBtn = document.getElementById('stop-timer');
    const timerDiv = document.getElementById('timer');
    const hintEl = document.getElementById('timer-hint');
    if (!startBtn || !timerDiv) return;

    let timerInterval = null;
    let timeLeft = 0;
    let totalSeconds = 0;

    function selectedSeconds() {
        const r = document.querySelector('input[name="pause-duration"]:checked');
        return r ? parseInt(r.value, 10) || 300 : 300;
    }

    function formatTime(sec) {
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    function resetUI() {
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
        startBtn.disabled = false;
        startBtn.innerHTML = '<i class="fas fa-clock mr-2"></i> Start pause';
        startBtn.classList.remove('bg-gray-400', 'cursor-not-allowed');
        startBtn.classList.add('btn-primary');
        stopBtn.classList.add('hidden');
        timerDiv.classList.add('hidden');
        timerDiv.classList.remove('animate-pulse', 'text-lg');
        hintEl.classList.add('hidden');
        document.querySelectorAll('input[name="pause-duration"]').forEach((el) => {
            el.disabled = false;
        });
    }

    function finish(message) {
        resetUI();
        timerDiv.classList.remove('hidden');
        timerDiv.classList.add('text-lg');
        timerDiv.innerHTML = `<span class="text-green-600 font-semibold">${message}</span>`;
    }

    startBtn.addEventListener('click', function () {
        if (timerInterval) return;

        totalSeconds = selectedSeconds();
        timeLeft = totalSeconds;

        startBtn.disabled = true;
        startBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> Pause running…';
        startBtn.classList.remove('btn-primary');
        startBtn.classList.add('bg-gray-400', 'cursor-not-allowed');
        stopBtn.classList.remove('hidden');
        timerDiv.classList.remove('hidden', 'text-lg');
        timerDiv.classList.add('animate-pulse');
        timerDiv.textContent = formatTime(timeLeft);
        hintEl.classList.remove('hidden');

        document.querySelectorAll('input[name="pause-duration"]').forEach((el) => {
            el.disabled = true;
        });

        timerInterval = setInterval(() => {
            timeLeft -= 1;
            if (timeLeft <= 0) {
                clearInterval(timerInterval);
                timerInterval = null;
                finish("Pause complete. How do you feel right now?");
                return;
            }
            timerDiv.textContent = formatTime(timeLeft);
        }, 1000);
    });

    stopBtn.addEventListener('click', function () {
        if (!timerInterval) return;
        clearInterval(timerInterval);
        timerInterval = null;
        finish("Nice work stopping when you were ready.");
    });
})();
