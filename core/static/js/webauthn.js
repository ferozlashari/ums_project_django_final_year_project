(function () {
  'use strict';

  // ---- base64url <-> ArrayBuffer helpers (WebAuthn's native format) ----
  function b64uToBuf(b64u) {
    const padded = b64u.replace(/-/g, '+').replace(/_/g, '/') + '=='.slice(0, (4 - b64u.length % 4) % 4);
    const raw = atob(padded);
    const buf = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
    return buf.buffer;
  }
  function bufToB64u(buf) {
    const bytes = new Uint8Array(buf);
    let str = '';
    for (let i = 0; i < bytes.byteLength; i++) str += String.fromCharCode(bytes[i]);
    return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  }

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
  }
  const CSRF_TOKEN = getCookie('csrftoken');

  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN || '' },
      body: body ? JSON.stringify(body) : '{}',
    }).then((r) => r.json().then((data) => ({ ok: r.ok, data })));
  }

  const supported = !!(window.PublicKeyCredential && navigator.credentials);

  function friendlyWebAuthnError(err) {
    const name = err && err.name;
    const msg = (err && err.message) || '';
    if (name === 'SecurityError' || /relying party|invalid domain|rp id/i.test(msg)) {
      return 'This page\'s address doesn\'t match the passkey configuration for this site. '
        + 'Make sure you are opening the site at the exact address it expects (see Settings for details).';
    }
    if (name === 'NotAllowedError') {
      return 'Passkey action was cancelled or timed out.';
    }
    return msg || 'Passkey action was cancelled or failed.';
  }


  // ---------------- Registration (Account Settings) ----------------
  const registerBtn = document.getElementById('webauthn-register-btn');
  if (registerBtn) {
    if (!supported) {
      registerBtn.disabled = true;
      registerBtn.title = 'This browser does not support passkeys (try Chrome, Edge, or Safari).';
    }
    registerBtn.addEventListener('click', async function () {
      const statusEl = document.getElementById('webauthn-status');
      const nameInput = document.getElementById('webauthn-device-name');
      const deviceName = (nameInput && nameInput.value.trim()) || 'My device';
      statusEl.textContent = "Follow your device's passkey prompt (fingerprint, face, or PIN)…";
      try {
        const begin = await postJSON('/webauthn/register/begin/');
        if (!begin.ok) throw new Error(begin.data.message || begin.data.error || 'Could not start registration.');
        const options = begin.data;
        options.challenge = b64uToBuf(options.challenge);
        options.user.id = b64uToBuf(options.user.id);
        if (options.excludeCredentials) {
          options.excludeCredentials.forEach((c) => { c.id = b64uToBuf(c.id); });
        }
        const credential = await navigator.credentials.create({ publicKey: options });
        const payload = {
          id: credential.id,
          rawId: bufToB64u(credential.rawId),
          type: credential.type,
          device_name: deviceName,
          response: {
            attestationObject: bufToB64u(credential.response.attestationObject),
            clientDataJSON: bufToB64u(credential.response.clientDataJSON),
          },
        };
        const complete = await postJSON('/webauthn/register/complete/', payload);
        if (!complete.ok) throw new Error(complete.data.message || complete.data.error || 'Verification failed.');
        statusEl.textContent = '✅ Device registered!';
        setTimeout(() => window.location.reload(), 900);
      } catch (err) {
        statusEl.textContent = '❌ ' + friendlyWebAuthnError(err);
      }
    });
  }

  // ---------------- Login-time verification ----------------
  const verifyBtn = document.getElementById('webauthn-verify-btn');
  if (verifyBtn) {
    if (!supported) {
      document.getElementById('webauthn-status').textContent =
        'This browser does not support passkeys. Try Chrome, Edge, or Safari.';
      verifyBtn.disabled = true;
    }
    verifyBtn.addEventListener('click', async function () {
      const statusEl = document.getElementById('webauthn-status');
      statusEl.textContent = "Follow your device's passkey prompt (fingerprint, face, or PIN)…";
      try {
        const begin = await postJSON('/webauthn/login/begin/');
        if (!begin.ok) throw new Error(begin.data.message || begin.data.error || 'Could not start verification.');
        const options = begin.data;
        options.challenge = b64uToBuf(options.challenge);
        if (options.allowCredentials) {
          options.allowCredentials.forEach((c) => { c.id = b64uToBuf(c.id); });
        }
        const assertion = await navigator.credentials.get({ publicKey: options });
        const payload = {
          id: assertion.id,
          rawId: bufToB64u(assertion.rawId),
          type: assertion.type,
          response: {
            authenticatorData: bufToB64u(assertion.response.authenticatorData),
            clientDataJSON: bufToB64u(assertion.response.clientDataJSON),
            signature: bufToB64u(assertion.response.signature),
            userHandle: assertion.response.userHandle ? bufToB64u(assertion.response.userHandle) : null,
          },
        };
        const complete = await postJSON('/webauthn/login/complete/', payload);
        if (!complete.ok) throw new Error(complete.data.message || complete.data.error || 'Verification failed.');
        statusEl.textContent = '✅ Verified! Redirecting…';
        window.location.href = complete.data.redirect || '/dashboard/';
      } catch (err) {
        statusEl.textContent = '❌ ' + friendlyWebAuthnError(err);
      }
    });
  }

  // ---------------- Reusable "verify identity" for biometric attendance/exam/online-class ----------------
  // Any button with data-webauthn-verify="1" triggers a WebAuthn prompt,
  // then submits its enclosing <form> (which the server checks was
  // recently verified via webauthn_recently_verified()).
  window.UMSBiometric = {
    supported: supported,
    async verifyThenSubmitForm(button) {
      const form = button.closest('form');
      const statusEl = form ? form.querySelector('[data-webauthn-status]') : null;
      const setStatus = (msg) => { if (statusEl) statusEl.textContent = msg; };
      if (!supported) {
        setStatus('This browser does not support passkeys on this device.');
        return;
      }
      button.disabled = true;
      setStatus("Follow your device's passkey prompt (fingerprint, face, or PIN)…");
      try {
        const begin = await postJSON('/webauthn/verify/begin/');
        if (!begin.ok) throw new Error(begin.data.message || begin.data.error || 'Could not start verification.');
        const options = begin.data;
        options.challenge = b64uToBuf(options.challenge);
        if (options.allowCredentials) {
          options.allowCredentials.forEach((c) => { c.id = b64uToBuf(c.id); });
        }
        const assertion = await navigator.credentials.get({ publicKey: options });
        const payload = {
          id: assertion.id,
          rawId: bufToB64u(assertion.rawId),
          type: assertion.type,
          response: {
            authenticatorData: bufToB64u(assertion.response.authenticatorData),
            clientDataJSON: bufToB64u(assertion.response.clientDataJSON),
            signature: bufToB64u(assertion.response.signature),
            userHandle: assertion.response.userHandle ? bufToB64u(assertion.response.userHandle) : null,
          },
        };
        const complete = await postJSON('/webauthn/verify/complete/', payload);
        if (!complete.ok) throw new Error(complete.data.message || complete.data.error || 'Verification failed.');
        setStatus('✅ Verified! Submitting…');
        if (form) form.submit();
      } catch (err) {
        setStatus('❌ ' + friendlyWebAuthnError(err));
        button.disabled = false;
      }
    },
  };

  document.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-webauthn-verify]');
    if (btn) {
      e.preventDefault();
      window.UMSBiometric.verifyThenSubmitForm(btn);
    }
  });
})();
