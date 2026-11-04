// Export function addresses, references and bounded C-like pseudocode.
// @category APKLab
import ghidra.app.util.headless.HeadlessScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import com.google.gson.*;
import java.nio.file.*;
import java.io.*;

public class ApkLabExport extends HeadlessScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Path output = Paths.get(args[0]);
        String selector = args[1];
        int limit = Integer.parseInt(args[2]);
        Files.createDirectories(output);
        Gson gson = new Gson();
        DecompInterface decompiler = new DecompInterface();
        if (!decompiler.openProgram(currentProgram)) throw new IOException("Cannot open decompiler");
        int total = 0, selected = 0, completed = 0;
        try (BufferedWriter writer = Files.newBufferedWriter(output.resolve("functions.jsonl"))) {
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext() && !monitor.isCancelled()) {
                Function f = functions.next();
                total++;
                JsonObject item = new JsonObject();
                String address = f.getEntryPoint().toString();
                item.addProperty("address", address);
                item.addProperty("rva", Long.toHexString(f.getEntryPoint().subtract(currentProgram.getImageBase())));
                item.addProperty("name", f.getName(true));
                item.addProperty("signature", f.getSignature().toString());
                item.addProperty("external", f.isExternal());
                item.addProperty("thunk", f.isThunk());
                if (limit > selected && !f.isExternal() &&
                        (selector.equals("*") || f.getName(true).contains(selector) || address.equals(selector))) {
                    selected++;
                    JsonArray refs = new JsonArray();
                    ReferenceIterator references = currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
                    int refCount = 0;
                    while (references.hasNext() && refCount < 200) {
                        Reference ref = references.next();
                        JsonObject row = new JsonObject();
                        row.addProperty("from", ref.getFromAddress().toString());
                        row.addProperty("type", ref.getReferenceType().toString());
                        Function caller = currentProgram.getFunctionManager().getFunctionContaining(ref.getFromAddress());
                        if (caller != null) row.addProperty("caller", caller.getName(true));
                        refs.add(row); refCount++;
                    }
                    item.add("references_to_entry", refs);
                    item.addProperty("references_truncated", references.hasNext());
                    DecompileResults result = decompiler.decompileFunction(f, 30, monitor);
                    item.addProperty("decompiled", result.decompileCompleted());
                    if (result.decompileCompleted() && result.getDecompiledFunction() != null) {
                        String name = address.replace(':', '_') + ".c";
                        Files.writeString(output.resolve(name), result.getDecompiledFunction().getC());
                        item.addProperty("pseudocode", name); completed++;
                    } else item.addProperty("error", result.getErrorMessage());
                }
                writer.write(gson.toJson(item)); writer.newLine();
            }
        } finally { decompiler.dispose(); }
        JsonObject summary = new JsonObject();
        summary.addProperty("ghidra_version", getGhidraVersion());
        summary.addProperty("language", currentProgram.getLanguageID().toString());
        summary.addProperty("image_base", currentProgram.getImageBase().toString());
        summary.addProperty("functions", total);
        summary.addProperty("selected", selected);
        summary.addProperty("decompiled", completed);
        summary.addProperty("selector", selector);
        summary.addProperty("analysis_timed_out", analysisTimeoutOccurred());
        summary.addProperty("limit", limit);
        summary.addProperty("note", "Reconstructed pseudocode, not original C++ source. Static entry references, not full runtime dispatch.");
        Files.writeString(output.resolve("summary.json"), gson.toJson(summary));
    }
}
