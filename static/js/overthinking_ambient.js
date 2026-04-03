(function () {
    const audio = document.getElementById('ambient-audio');
    const playBtn = document.getElementById('ambient-play');
    const stopBtn = document.getElementById('ambient-stop');
    const volSlider = document.getElementById('ambient-volume');
    const statusEl = document.getElementById('ambient-status');
    const fileInput = document.getElementById('ambient-file');

    if (!audio || !playBtn || !stopBtn || !volSlider) return;

    let endTimer = null;
    let objectUrl = null;

    const defaultSrc = audio.getAttribute('src') || '';

    function selectedMinutes() {
        const r = document.querySelector('input[name="ambient-mp3-minutes"]:checked');
        const n = r ? parseInt(r.value, 10) : 3;
        return Math.min(5, Math.max(1, n || 3));
    }

    function setStatus(msg, isErr) {
        if (!statusEl) return;
        statusEl.textContent = msg;
        statusEl.classList.toggle('text-red-600', !!isErr);
        statusEl.classList.toggle('text-gray-500', !isErr);
    }

    function applyVolume() {
        const v = Math.max(0, Math.min(1, parseInt(volSlider.value, 10) / 100));
        audio.volume = v;
    }

    function clearEndTimer() {
        if (endTimer) {
            clearTimeout(endTimer);
            endTimer = null;
        }
    }

    function stopPlayback(message) {
        clearEndTimer();
        audio.pause();
        audio.currentTime = 0;
        playBtn.disabled = false;
        if (message) {
            setStatus(message);
        }
    }

    function revokeObjectUrl() {
        if (objectUrl) {
            URL.revokeObjectURL(objectUrl);
            objectUrl = null;
        }
    }

    if (fileInput) {
        fileInput.addEventListener('change', () => {
            const f = fileInput.files && fileInput.files[0];
            revokeObjectUrl();
            stopPlayback('');
            if (!f) {
                audio.src = defaultSrc;
                audio.load();
                setStatus('Using the project MP3 from static/audio/.');
                return;
            }
            objectUrl = URL.createObjectURL(f);
            audio.src = objectUrl;
            audio.load();
            setStatus(`Ready: “${f.name}”. Tap Play.`);
        });
    }

    playBtn.addEventListener('click', async () => {
        applyVolume();
        audio.loop = true;
        clearEndTimer();

        if (!audio.src) {
            setStatus('No audio source. Choose an MP3 above or ensure static/audio/ has the default track.', true);
            return;
        }

        try {
            audio.load();
            await audio.play();
        } catch (e) {
            const err = audio.error;
            let detail = err ? ` (code ${err.code})` : '';
            if (err && err.code === 4) {
                detail = ' — file missing, wrong path, or not a supported MP3.';
            }
            setStatus(
                `Could not play.${detail} Check static/audio/ and the template audio src, or use “Choose file”.`,
                true
            );
            return;
        }

        playBtn.disabled = true;
        const mins = selectedMinutes();
        const ms = mins * 60 * 1000;
        setStatus(`Playing… ${mins} min (or tap Stop).`);

        endTimer = setTimeout(() => {
            stopPlayback(`Finished after ${mins} min.`);
        }, ms);
    });

    stopBtn.addEventListener('click', () => {
        stopPlayback('Stopped.');
    });

    volSlider.addEventListener('input', () => {
        applyVolume();
    });

    audio.addEventListener('error', () => {
        clearEndTimer();
        playBtn.disabled = false;
        setStatus(
            'Cannot load default MP3. Use “Choose file”, or add/rename the track under static/audio/ to match the template.',
            true
        );
    });
})();
