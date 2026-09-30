/* Russian phone mask shared by order creation and contact editing. */
(function () {
  const template = '+7 999 000-00-00';
  function digits(value) {
    const text = String(value || '');
    let result = text.replace(/\D/g, '');
    if ((result[0] === '7' || result[0] === '8') && (result.length > 10 || /^\s*\+7|^\s*[78]\D/.test(text))) result = result.slice(1);
    return result.slice(0, 10);
  }
  function format(value) {
    let result = '+7 ';
    for (let i = 0; i < value.length; i++) {
      if (i === 3) result += ' ';
      if (i === 6 || i === 8) result += '-';
      result += value[i];
    }
    return result;
  }
  function position(value, count) {
    if (!count) return 3;
    let seen = 0;
    for (let i = 3; i < value.length; i++) {
      if (/\d/.test(value[i]) && ++seen === count) return i + 1;
    }
    return value.length;
  }
  if (typeof module !== 'undefined') module.exports = {digits, format, position};
  if (typeof document === 'undefined') return;
  const selector = 'input[name="customer_contact"][type="tel"]';
  const masks = new WeakMap();
  function paint(input, local, caret) {
    input.value = local.length ? format(local) : '';
    input.setCustomValidity(local.length && local.length !== 10 ? 'Введите номер полностью: +7 и 10 цифр.' : '');
    const hint = masks.get(input);
    if (hint) {
      const style = getComputedStyle(input);
      for (const key of ['font', 'letterSpacing', 'padding', 'borderWidth', 'lineHeight']) hint.style[key] = style[key];
      hint.style.top = style.marginTop;
      const prefix = input.value;
      hint.firstChild.textContent = prefix;
      hint.lastChild.textContent = template.slice(prefix.length);
    }
    if (caret != null) input.setSelectionRange(position(input.value, caret), position(input.value, caret));
  }
  function init(input) {
    if (masks.has(input)) return;
    const wrapper = document.createElement('span');
    wrapper.className = 'phone-mask';
    input.before(wrapper);
    wrapper.append(input);
    const hint = document.createElement('span');
    hint.className = 'phone-mask-hint';
    hint.setAttribute('aria-hidden', 'true');
    hint.append(document.createElement('span'), document.createElement('span'));
    wrapper.append(hint);
    masks.set(input, hint);
    input.removeAttribute('maxlength'); // Pasted punctuation must not truncate the last digits.
    input.placeholder = '';
    input.pattern = '\\+7 [0-9]{3} [0-9]{3}-[0-9]{2}-[0-9]{2}';
    input.title = 'Номер телефона: +7 и 10 цифр';
    paint(input, digits(input.value));
  }
  function selection(input) {
    const count = end => input.value.slice(3, Math.max(3, end)).replace(/\D/g, '').length;
    return [count(input.selectionStart), count(input.selectionEnd)];
  }
  function insert(input, text) {
    const local = digits(input.value), [start, end] = selection(input);
    const raw = String(text).replace(/\D/g, '');
    if (!raw) return;
    // A complete pasted number replaces the selection; a single digit is local input.
    const added = raw.length >= 11 || /^\s*\+7|^\s*[78]\D/.test(text) ? digits(text) : raw;
    const next = (local.slice(0, start) + added + local.slice(end)).slice(0, 10);
    paint(input, next, Math.min(start + added.length, 10));
  }
  document.addEventListener('focusin', event => {
    if (!event.target.matches(selector)) return;
    const input = event.target;
    init(input);
    paint(input, digits(input.value), input.value ? undefined : 0);
  });
  document.addEventListener('focusout', event => {
    if (event.target.matches(selector)) paint(event.target, digits(event.target.value));
  });
  document.addEventListener('beforeinput', event => {
    const input = event.target;
    if (!input.matches(selector) || !event.cancelable || event.isComposing) return;
    init(input);
    if (event.inputType.startsWith('delete')) {
      event.preventDefault();
      let [start, end] = selection(input);
      if (start === end) {
        if (event.inputType.includes('Backward')) start = Math.max(0, start - 1);
        else end++;
      }
      const local = digits(input.value);
      paint(input, local.slice(0, start) + local.slice(end), start);
    } else if (event.inputType === 'insertText' && event.data != null) {
      event.preventDefault();
      // Accept 7/8 as the country prefix when starting a number.
      if (!digits(input.value) && /^[78]$/.test(event.data)) return;
      insert(input, event.data);
    }
  });
  document.addEventListener('paste', event => {
    if (!event.target.matches(selector)) return;
    event.preventDefault();
    init(event.target);
    insert(event.target, event.clipboardData.getData('text'));
  });
  document.addEventListener('input', event => {
    if (!event.target.matches(selector)) return;
    init(event.target);
    const [caret] = selection(event.target);
    const local = digits(event.target.value);
    const atEnd = event.target.selectionStart === event.target.value.length;
    paint(event.target, local, atEnd ? local.length : caret);
  });
  document.addEventListener('reset', event => {
    setTimeout(() => event.target.querySelectorAll(selector).forEach(input => {
      init(input);
      paint(input, digits(input.value));
    }), 0);
  });
  document.addEventListener('submit', event => {
    const inputs = event.target.querySelectorAll(selector);
    for (const input of inputs) {
      init(input);
      paint(input, digits(input.value));
      if (!input.reportValidity()) {
        event.preventDefault();
        event.stopImmediatePropagation();
        break;
      }
    }
  }, true);
  const scan = () => document.querySelectorAll(selector).forEach(init);
  new MutationObserver(scan).observe(document.body, {childList: true, subtree: true});
  window.addEventListener('resize', () => document.querySelectorAll(selector).forEach(input => paint(input, digits(input.value))));
  scan();
})();
