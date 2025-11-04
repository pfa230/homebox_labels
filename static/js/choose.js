function onTemplateChange() {
  const form = document.getElementById('options-form');
  if (!form) return;
  form.dataset.trigger = 'template';
  form.submit();
}

function onOptionChange(select) {
  const form = document.getElementById('options-form');
  if (!form) return;
  const hiddenFieldName = `pending_${select.name}`;
  let hidden = document.getElementById(hiddenFieldName);
  if (!hidden) {
    hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.id = hiddenFieldName;
    hidden.name = select.name;
    form.appendChild(hidden);
  }
  hidden.value = select.value;
  form.dataset.trigger = 'option';
  form.submit();
}
