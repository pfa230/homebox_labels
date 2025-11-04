function onTemplateChange() {
  const form = document.getElementById('options-form');
  if (!form) return;
  const originalAction = form.action;
  form.action = '/choose';
  form.submit();
  form.action = originalAction;
}
