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
  const selects = document.querySelectorAll(`select[name^="option_${optionName}_"]`);
  selects.forEach((sel) => {
    sel.value = value;
  });
}
