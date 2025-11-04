function onTemplateChange() {
  const form = document.getElementById('options-form');
  if (!form) return;
  const pageType = form.dataset.pageType || 'locations';
  const originalAction = form.action;
  form.action = `/${pageType}/choose`;
  form.submit();
  form.action = originalAction;
}
