/**
 * Shared CRUD helpers for admin modal dialogs.
 * All mutation forms call existing /api/v1/* endpoints.
 */

// ─── CSRF ─────────────────────────────────────────────────────────────────────
function getCsrf() {
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

// ─── Fetch helpers ─────────────────────────────────────────────────────────────
async function apiPost(url, body) {
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-csrf-token': getCsrf() },
        body: JSON.stringify(body),
    });
}

async function apiPatch(url, body) {
    return fetch(url, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'x-csrf-token': getCsrf() },
        body: JSON.stringify(body),
    });
}

async function apiDelete(url) {
    return fetch(url, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json', 'x-csrf-token': getCsrf() },
    });
}

async function apiPostForm(url, formData) {
    // No Content-Type header — browser sets multipart boundary automatically
    return fetch(url, {
        method: 'POST',
        headers: { 'x-csrf-token': getCsrf() },
        body: formData,
    });
}

// ─── Modal helpers ─────────────────────────────────────────────────────────────
function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.showModal();
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.close();
}

function setModalError(modalId, msg) {
    const el = document.getElementById('err-' + modalId.replace('modal-', ''));
    if (!el) return;
    if (msg) {
        el.textContent = msg;
        el.classList.remove('hidden');
    } else {
        el.textContent = '';
        el.classList.add('hidden');
    }
}

function clearModalError(modalId) {
    setModalError(modalId, '');
}

// ─── Select population ─────────────────────────────────────────────────────────
const _selectCache = {};

/**
 * Populate a <select> element from an API endpoint.
 * @param {HTMLSelectElement} selectEl
 * @param {string} url  - API URL returning an array
 * @param {function} labelFn  - item => display string
 * @param {function} valueFn  - item => option value
 * @param {boolean} addBlank  - prepend a blank option
 */
async function populateSelect(selectEl, url, labelFn, valueFn, addBlank = true) {
    if (_selectCache[url]) {
        _buildSelectOptions(selectEl, _selectCache[url], labelFn, valueFn, addBlank);
        return;
    }
    selectEl.disabled = true;
    try {
        const res = await fetch(url, { headers: { 'x-csrf-token': getCsrf() } });
        if (!res.ok) throw new Error('Failed to load');
        const data = await res.json();
        _selectCache[url] = data;
        _buildSelectOptions(selectEl, data, labelFn, valueFn, addBlank);
    } catch (e) {
        console.error('populateSelect error', url, e);
    } finally {
        selectEl.disabled = false;
    }
}

function _buildSelectOptions(selectEl, items, labelFn, valueFn, addBlank) {
    const currentVal = selectEl.value;
    selectEl.innerHTML = '';
    if (addBlank) {
        const blank = document.createElement('option');
        blank.value = '';
        blank.textContent = '— select —';
        selectEl.appendChild(blank);
    }
    items.forEach(item => {
        const opt = document.createElement('option');
        opt.value = valueFn(item);
        opt.textContent = labelFn(item);
        selectEl.appendChild(opt);
    });
    if (currentVal) selectEl.value = currentVal;
}

// ─── Form helpers ──────────────────────────────────────────────────────────────
/** Collect all form inputs into a plain object, skipping empty strings for optional fields. */
function formToObject(formEl, optionalFields = []) {
    const data = {};
    new FormData(formEl).forEach((val, key) => {
        if (val === '' && optionalFields.includes(key)) return;
        data[key] = val;
    });
    // Handle checkboxes — FormData only includes checked ones
    formEl.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        data[cb.name] = cb.checked;
    });
    return data;
}

/** Set a loading state on the submit button. Returns a restore function. */
function setSubmitting(formId, loading) {
    const btn = document.querySelector(`[form="${formId}"][type="submit"]`);
    if (!btn) return () => {};
    if (loading) {
        btn._origText = btn.textContent;
        btn.textContent = 'Saving…';
        btn.disabled = true;
    } else {
        btn.textContent = btn._origText || 'Save';
        btn.disabled = false;
    }
}

/** Parse an API error response into a readable string. */
async function parseApiError(res) {
    try {
        const body = await res.json();
        if (body.detail) {
            if (typeof body.detail === 'string') return body.detail;
            if (Array.isArray(body.detail)) return body.detail.map(e => e.msg || JSON.stringify(e)).join('; ');
        }
    } catch (_) {}
    return `Error ${res.status}`;
}

// ─── Local datetime helper ─────────────────────────────────────────────────────
/** Returns current datetime as a string suitable for datetime-local inputs. */
function nowLocalISO() {
    const d = new Date();
    d.setSeconds(0, 0);
    return d.toISOString().slice(0, 16);
}
