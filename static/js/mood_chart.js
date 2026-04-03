// Mood trend chart (used on Mood Tracker page)
async function loadMoodChart() {
    const canvas = document.getElementById('moodChart');
    if (!canvas || typeof Chart === 'undefined') return;

    try {
        const response = await fetch('/api/mood_data');
        const data = await response.json();

        const ctx = canvas.getContext('2d');
        const moodMap = { happy: 4, neutral: 3, sad: 2, stressed: 1, anxious: 1 };
        const labels = data.map((d) => d.date);
        const values = data.map((d) => moodMap[d.mood] || 3);

        new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Mood level',
                        data: values,
                        borderColor: '#667eea',
                        backgroundColor: 'rgba(102, 126, 234, 0.1)',
                        tension: 0.4,
                        fill: true,
                        pointBackgroundColor: '#667eea',
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        pointRadius: 6,
                        pointHoverRadius: 8,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 4,
                        ticks: {
                            callback(value) {
                                const moods = ['', 'Stressed/Anxious', 'Sad', 'Neutral', 'Happy'];
                                return moods[value] || '';
                            },
                            font: { size: 12 },
                        },
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                    },
                    x: {
                        ticks: { font: { size: 12 } },
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                    },
                },
            },
        });
    } catch (error) {
        console.error('Error loading mood data:', error);
        const ctx = canvas.getContext('2d');
        ctx.font = '16px sans-serif';
        ctx.fillStyle = '#666';
        ctx.textAlign = 'center';
        ctx.fillText('No mood data to chart yet — log a few days to see trends', canvas.width / 2, canvas.height / 2);
    }
}

document.addEventListener('DOMContentLoaded', loadMoodChart);
