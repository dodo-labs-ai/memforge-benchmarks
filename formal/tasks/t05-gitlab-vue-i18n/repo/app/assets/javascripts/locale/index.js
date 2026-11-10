const identity = (text) => text;

export const __ = identity;
export const s__ = (keyOrNamespace, key) => key || keyOrNamespace.split('|').pop();
export const n__ = (singular, plural, count) => (count === 1 ? singular : plural);
export const sprintf = (input, parameters) =>
  Object.entries(parameters).reduce((text, [name, value]) => text.replace(`%{${name}}`, value), input);
