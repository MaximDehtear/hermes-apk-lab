// For the Frida CLI/REPL Java bridge. A custom Frida agent may need frida-java-bridge bundled.
// Select the exact overload, class loader and field semantics before use.
const CONFIG = {
  className: 'example.obfuscated.a', method: 'b', overload: ['java.lang.String'],
  label: 'hypothesis_encodeRequest', captureStringArgs: [], captureStringReturn: false,
  maxCharacters: 128, maxEvents: 200
};
let sequence = 0;
function emit(value) {
  if (sequence >= CONFIG.maxEvents) return;
  send(Object.assign({tag: 'APKLAB', seq: ++sequence, time: Date.now(), label: CONFIG.label}, value));
}
Java.perform(function () {
  try {
    const type = Java.use(CONFIG.className);
    const method = type[CONFIG.method].overload(...CONFIG.overload);
    method.implementation = function (...args) {
      const call = Process.getCurrentThreadId() + ':' + Date.now();
      const values = {};
      for (const index of CONFIG.captureStringArgs) {
        // Do not call arbitrary app toString() methods: these can have side effects.
        values[index] = typeof args[index] === 'string' ? args[index].slice(0, CONFIG.maxCharacters) : '<not a JS string>';
      }
      emit({event: 'enter', call, values});
      try {
        const result = method.call(this, ...args);
        emit({event: 'leave', call, result: CONFIG.captureStringReturn && typeof result === 'string' ? result.slice(0, CONFIG.maxCharacters) : '<not captured>'});
        return result;
      } catch (error) {
        emit({event: 'throw', call});
        throw error;
      }
    };
    emit({event: 'attached', original: CONFIG.className + '.' + CONFIG.method, overload: CONFIG.overload});
  } catch (error) { emit({event: 'attach_error', error: String(error)}); }
});
