function onTemplateChange() {
  const form = document.getElementById('options-form');
  if (!form) return;
  const pageType = form.dataset.pageType || 'locations';
  const originalAction = form.action;
  form.action = `/${pageType}/choose`;
  form.submit();
  form.action = originalAction;
}

function applyOptionToAll(optionName) {
  const bulkSelect = document.getElementById(`bulk_${optionName}`);
  if (!bulkSelect) return;
  const value = bulkSelect.value;
  document
    .querySelectorAll(`select[name^="option_${optionName}_"]`)
    .forEach((sel) => {
      sel.value = value;
    });
}

function onCopiesChange() {
  const form = document.getElementById('options-form');
  if (!form) return;
  const pageType = form.dataset.pageType || 'locations';
  const originalAction = form.action;
  form.action = `/${pageType}/choose`;
  form.submit();
  form.action = originalAction;
}
