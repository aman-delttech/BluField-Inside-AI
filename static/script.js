let lastExtractionResponse = null;
let currentMeterType = null;

// File Upload Visual Feedback
const fileInputs = document.querySelectorAll('.file-input');
fileInputs.forEach(input => {
    input.addEventListener('change', function() {
        const msg = this.previousElementSibling;
        if (this.files && this.files.length > 0) {
            msg.textContent = this.files[0].name;
            msg.style.color = 'var(--primary-red)';
            msg.style.fontWeight = '600';
            this.parentElement.classList.add('is-active');
        } else {
            msg.textContent = 'Choose file or drag here';
            msg.style.color = '#64748B';
            msg.style.fontWeight = '500';
            this.parentElement.classList.remove('is-active');
        }
    });

    // Drag and drop effects
    const dropArea = input.parentElement;
    ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, () => dropArea.classList.add('is-active'), false);
    });
    ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, () => {
            if (!input.files || input.files.length === 0) {
                dropArea.classList.remove('is-active');
            }
        }, false);
    });
});


document.getElementById('extract-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const form = e.target;
    const formData = new FormData(form);
    const meterType = formData.get('meter_type');
    currentMeterType = meterType;
    
    const endpoint = meterType === 'old' ? '/old-meter' : '/new-meter';
    
    showLoading("Extracting meter data using local OCR model. This may take 10-40 seconds...");
    
    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to extract data');
        }
        
        lastExtractionResponse = await response.json();
        
        // Hide empty states
        document.getElementById('extraction-empty').style.display = 'none';
        
        // Reset verification column
        document.getElementById('verification-content').style.display = 'none';
        document.getElementById('verification-empty').style.display = 'block';
        
        // Show extraction content
        displayExtraction(lastExtractionResponse);
        document.getElementById('extraction-content').style.display = 'block';
    } catch (error) {
        alert("Error during extraction: " + error.message);
    } finally {
        hideLoading();
    }
});

document.getElementById('verify-btn').addEventListener('click', async () => {
    if (!lastExtractionResponse) return;
    
    const endpoint = currentMeterType === 'old' ? '/verify/old-meter' : '/verify/new-meter';
    
    showLoading("Verifying data against NAMA Image AI sheet...");
    
    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(lastExtractionResponse)
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to verify data');
        }
        
        const verificationData = await response.json();
        
        // Hide empty state and show table
        document.getElementById('verification-empty').style.display = 'none';
        displayVerification(verificationData);
        document.getElementById('verification-content').style.display = 'block';
        
    } catch (error) {
        alert("Error during verification: " + error.message);
    } finally {
        hideLoading();
    }
});

function displayExtraction(data) {
    const displayEl = document.getElementById('extraction-data');
    
    let html = `<strong>Account No:</strong> ${data.account_no || 'N/A'}\n`;
    html += `<strong>Meter:</strong> ${data.meter}\n`;
    html += `<strong>ICCID:</strong> ${data.iccid !== null ? data.iccid : 'null'}\n`;
    html += `<strong>Meter No:</strong> ${data.meter_no || 'null'}\n`;
    html += `<strong>Meter Phase:</strong> ${data.meter_phase || 'null'}\n`;
    html += `<strong>Meter Reading:</strong> ${data.meter_reading || 'null'}\n`;
    
    // Inject custom capsule element if needs review
    if (data.needs_review && Object.keys(data.needs_review).length > 0) {
        html += `\n<div style="margin-top: 15px; padding-top: 15px; border-top: 1px dashed var(--border-color);">`;
        html += `<h3 class="capsule-heading">Needs Review</h3>\n`;
        for (const [key, values] of Object.entries(data.needs_review)) {
            html += `  <strong>${key}:</strong> [${values.join(', ')}]\n`;
        }
        html += `</div>`;
    }
    
    displayEl.innerHTML = html;
}

function displayVerification(data) {
    const summaryEl = document.getElementById('verification-summary');
    const { match, checked, rate } = data.summary;
    const ratePct = (rate * 100).toFixed(1);
    
    // Summary display removed per user request
    
    const tbody = document.getElementById('verification-tbody');
    tbody.innerHTML = '';
    
    for (const [field, details] of Object.entries(data.fields)) {
        const tr = document.createElement('tr');
        
        const tdField = document.createElement('td');
        tdField.textContent = field;
        
        const tdExtracted = document.createElement('td');
        tdExtracted.textContent = details.extracted !== null ? details.extracted : 'null';
        
        const tdExpected = document.createElement('td');
        tdExpected.textContent = details.expected !== null ? details.expected : 'null';
        
        const tdStatus = document.createElement('td');
        let statusText = details.status;
        if (details.similarity !== undefined && details.status === 'MISMATCH') {
            statusText += ` (${(details.similarity * 100).toFixed(0)}% sim)`;
        }
        tdStatus.textContent = statusText;
        tdStatus.className = `status-${details.status}`;
        
        tr.appendChild(tdField);
        tr.appendChild(tdExtracted);
        tr.appendChild(tdExpected);
        tr.appendChild(tdStatus);
        
        tbody.appendChild(tr);
    }
}

function showLoading(text) {
    document.getElementById('loading-text').textContent = text;
    document.getElementById('loading-overlay').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loading-overlay').style.display = 'none';
}
