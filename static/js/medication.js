const form = document.getElementById('medication-form');
const resultDiv = document.getElementById('medication-result');
const medicineInput = document.getElementById('medicine-input');

function escapeHtml(str) {
    return (str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function renderResultCard(item) {
    return `
        <div class="bg-white card-shadow rounded-xl p-8">
            <div class="flex items-center justify-between mb-6">
                <h2 class="text-xl font-semibold text-gray-900">${escapeHtml(item.drug_name || 'Medication')}</h2>
                <span class="text-xs px-2 py-1 rounded bg-indigo-100 text-indigo-700 uppercase">Educational summary</span>
            </div>
            <div class="space-y-4 text-sm text-gray-700">
                <p><span class="font-semibold text-gray-900">Use:</span> ${escapeHtml(item.use || 'Not available')}</p>
                <p><span class="font-semibold text-gray-900">Side effects:</span> ${escapeHtml(item.side_effects || 'Not available')}</p>
            </div>
        </div>
    `;
}

function renderMessage(message, type = 'info') {
    const classes = type === 'error'
        ? 'bg-red-50 border-red-200 text-red-700'
        : 'bg-blue-50 border-blue-200 text-blue-700';
    return `<div class="border rounded-lg p-4 ${classes}">${escapeHtml(message)}</div>`;
}

async function submitMedicationForm() {
    if (!form || !resultDiv) return;
    resultDiv.innerHTML = renderMessage('Generating a short summary…');

    try {
        const formData = new FormData(form);
        const response = await fetch('/api/medication_info', {
            method: 'POST',
            body: formData
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            resultDiv.innerHTML = renderMessage(
                data.error || `Something went wrong (HTTP ${response.status}). Try logging in again if your session expired.`,
                'error'
            );
            return;
        }

        if (!data.found) {
            resultDiv.innerHTML = `
                ${renderMessage(data.message || 'Data not found', 'error')}
                ${data.disclaimer ? renderMessage(data.disclaimer) : ''}
            `;
            return;
        }

        let results = Array.isArray(data.results) ? data.results : [];
        if (results.length === 0 && data.drug_name) {
            results = [data];
        }
        const cards = results.map(renderResultCard).join('');
        const disclaimer = data.disclaimer ? renderMessage(data.disclaimer) : '';

        resultDiv.innerHTML = `${cards}${disclaimer}`;
    } catch (err) {
        console.error(err);
        resultDiv.innerHTML = renderMessage('Unable to fetch medication information right now.', 'error');
    }
}

form.addEventListener('submit', (e) => {
    e.preventDefault();
    submitMedicationForm();
});

// Enter in the text field must trigger the same lookup (explicit for all browsers)
if (medicineInput && form) {
    medicineInput.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
        } else {
            submitMedicationForm();
        }
    });
}
