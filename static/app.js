// Read the current form token so HTMX POSTs retain Django's CSRF protection.
document.addEventListener("htmx:configRequest", function (event) {
  const token = document.querySelector('input[name="csrfmiddlewaretoken"]');
  if (token && new URL(event.detail.path, window.location.href).origin === window.location.origin) {
    event.detail.headers["X-CSRFToken"] = token.value;
  }
});

function updateStepInputs(root = document) {
  root.querySelectorAll('[data-step-action]').forEach(action => {
    const input = action.form.querySelector('[data-step-input]');
    if (!input) return;
    const usesInput = ['fill', 'select'].includes(action.value);
    input.closest('p').hidden = !usesInput;
    input.disabled = !usesInput;
    input.required = usesInput;
  });
}
document.addEventListener('DOMContentLoaded', () => updateStepInputs());
document.addEventListener('htmx:load', () => updateStepInputs());
document.addEventListener('change', event => {
  if (event.target.matches('[data-step-action]')) updateStepInputs();
});
