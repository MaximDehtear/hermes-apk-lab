// Frida runtime template. Edit CONFIG from evidence, then attach to the selected app.
// Does not replace functions, change returns, spawn or restart the process.
const CONFIG = {
  library: 'libexample.so',
  symbol: 'replace_with_exact_export', // Use null and module-relative rva for stripped code.
  rva: null, // Example '0x1234'; Ghidra entry minus image base, verified against exact .so hash.
  label: 'hypothesis_requestSerializer',
  cstringArgs: [], // Explicit ABI-verified argument indices only; default captures no payload.
  maxBytes: 128,
  maxEvents: 200
};
let sequence = 0;
const listeners = new Map();
function emit(value) {
  if (sequence >= CONFIG.maxEvents) return;
  send(Object.assign({tag: 'APKLAB', seq: ++sequence, time: Date.now(), label: CONFIG.label}, value));
}
const observer = Process.attachModuleObserver({
  onAdded(module) {
    if (module.name !== CONFIG.library || listeners.has(module.base.toString())) return;
    try {
      const address = CONFIG.symbol ? module.getExportByName(CONFIG.symbol) : module.base.add(ptr(CONFIG.rva));
      const range = Process.findRangeByAddress(address);
      if (!range || !range.protection.includes('x')) throw new Error('Target is not executable');
      const listener = Interceptor.attach(address, {
        onEnter(args) {
          this.callId = Process.getCurrentThreadId() + ':' + Date.now();
          const values = {};
          for (const index of CONFIG.cstringArgs) {
            try { values[index] = args[index].readUtf8String(CONFIG.maxBytes); }
            catch (_) { values[index] = '<unreadable or not a UTF-8 C string>'; }
          }
          emit({event: 'enter', call: this.callId, thread: Process.getCurrentThreadId(), address: address.toString(), values});
        },
        onLeave(retval) {
          emit({event: 'leave', call: this.callId, return_bits: retval.toString()});
        }
      });
      listeners.set(module.base.toString(), listener);
      emit({event: 'attached', module: module.path, base: module.base.toString(), address: address.toString()});
    } catch (error) { emit({event: 'attach_error', error: String(error)}); }
  },
  onRemoved(module) {
    const key = module.base.toString();
    if (listeners.has(key)) { listeners.get(key).detach(); listeners.delete(key); }
  }
});
