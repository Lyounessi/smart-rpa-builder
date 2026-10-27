// Read the current form token so HTMX POSTs retain Django's CSRF protection.
document.addEventListener("htmx:configRequest", function (event) {
  const token = document.querySelector('input[name="csrfmiddlewaretoken"]');
  if (token && new URL(event.detail.path, window.location.href).origin === window.location.origin) {
    event.detail.headers["X-CSRFToken"] = token.value;
  }
});
