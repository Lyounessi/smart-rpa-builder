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
    const output = action.form.querySelector('[data-step-output]');
    if (output) {
      const readsText = action.value === 'read_text';
      output.closest('p').hidden = !readsText;
      output.disabled = !readsText;
      output.required = readsText;
    }
  });
}
document.addEventListener('DOMContentLoaded', () => updateStepInputs());
document.addEventListener('htmx:load', () => updateStepInputs());
document.addEventListener('change', event => {
  if (event.target.matches('[data-step-action]')) updateStepInputs();
});

let runSelectionFocus = null;
document.addEventListener('htmx:beforeRequest', event => {
  const field = event.detail.elt;
  if (field && ['build', 'dataset'].includes(field.name)) runSelectionFocus = field.name;
});
document.addEventListener('htmx:afterSwap', event => {
  if (event.detail.target.id !== 'run-dialog-content') return;
  const dialog = document.getElementById('robot-run-dialog');
  if (dialog && !dialog.open) dialog.showModal();
  const panel = event.detail.target;
  const focus = panel.querySelector('[aria-invalid="true"]') ||
    (runSelectionFocus && panel.querySelector('[name="' + runSelectionFocus + '"]')) || panel.querySelector('select');
  if (focus) focus.focus();
  runSelectionFocus = null;
});
document.addEventListener('click', event => {
  const close = event.target.closest('[data-close-run-dialog]');
  const dialog = document.getElementById('robot-run-dialog');
  if (close && dialog && dialog.open) {
    event.preventDefault();
    dialog.close();
  }
});
