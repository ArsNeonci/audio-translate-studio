import { open } from "node:fs/promises";
import path from "node:path";
import { licenseDenial } from "@/lib/server/license";

export async function savedFileResponse(request: Request, file: string, download = false) {
  if (!download) {const denied = await licenseDenial(false); if (denied) return denied;}
  const handle = await open(/*turbopackIgnore: true*/ file, "r");
  try {
    const info = await handle.stat();
    const extension = path.extname(file).slice(1);
    const mime: Record<string, string> = {wav: "audio/wav", m4a: "audio/mp4", md: "text/markdown; charset=utf-8", txt: "text/plain; charset=utf-8", json: "application/json; charset=utf-8", jsonl: "application/x-ndjson; charset=utf-8"};
    const headers: Record<string, string> = {"Content-Type": mime[extension] || "application/octet-stream", "Content-Disposition": `${download ? "attachment" : "inline"}; filename="${path.basename(file)}"`, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"};
    const params = new URL(request.url).searchParams;
    if (params.get("preview") === "1" && ["md", "txt", "json", "jsonl"].includes(extension)) {
      const offset = Number(params.get("offset") || 0);
      if (!Number.isSafeInteger(offset) || offset < 0 || offset > info.size) {
        await handle.close(); return Response.json({error: "Invalid preview offset"}, {status: 400});
      }
      const buffer = Buffer.alloc(Math.min(65536, info.size-offset));
      const {bytesRead} = await handle.read(buffer, 0, buffer.length, offset);
      let used = bytesRead;
      if (offset+used < info.size) {
        const newline = buffer.subarray(0, used).lastIndexOf(10);
        if (newline >= 0) used = newline+1;
        else {
          let lead = used-1;
          while (lead >= 0 && (buffer[lead]&0xc0) === 0x80) lead--;
          const byte = buffer[lead];
          const width = byte >= 0xf0 ? 4 : byte >= 0xe0 ? 3 : byte >= 0xc0 ? 2 : 1;
          if (lead >= 0 && lead+width > used) used = lead;
        }
      }
      let content = buffer.subarray(0, used).toString("utf8");
      if (extension === "json" && offset === 0 && used === info.size) {
        try { content = JSON.stringify(JSON.parse(content), null, 2); } catch { /* Plain text fallback. */ }
      }
      const next = offset+used < info.size ? offset+used : null;
      await handle.close();
      return Response.json({content, offset, next_offset: next, size: info.size}, {headers: {"Cache-Control": "no-store"}});
    }
    let start = 0, end = info.size-1, status = 200;
    headers["Accept-Ranges"] = "bytes";
    const range = request.headers.get("range");
    if (range) {
      const match = /^bytes=(\d*)-(\d*)$/.exec(range);
      if (match && (match[1] || match[2])) {
        if (!match[1]) start = Math.max(0, info.size-Number(match[2]));
        else { start = Number(match[1]); if (match[2]) end = Math.min(end, Number(match[2])); }
      }
      if (!match || (!match[1] && !match[2]) || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= info.size) {
        await handle.close(); return new Response(null, {status: 416, headers: {"Content-Range": `bytes */${info.size}`}});
      }
      status = 206; headers["Content-Range"] = `bytes ${start}-${end}/${info.size}`;
    }
    headers["Content-Length"] = String(Math.max(0, end-start+1));
    if (!info.size) { await handle.close(); return new Response(null, {headers}); }
    // FileHandle reads obey web-stream backpressure. Guard cancellation before
    // enqueue/close so an aborted audio request cannot write to a closed stream.
    let cursor = start;
    let stopped = false;
    let closing: Promise<void> | undefined;
    const close = () => closing ?? (closing = handle.close());
    const stream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        if (stopped) return;
        try {
          const buffer = Buffer.alloc(Math.min(65536, end-cursor+1));
          const {bytesRead} = await handle.read(buffer, 0, buffer.length, cursor);
          if (stopped) return;
          if (bytesRead) {cursor += bytesRead; controller.enqueue(buffer.subarray(0, bytesRead));}
          if (!bytesRead || cursor > end) {stopped = true; controller.close(); await close();}
        } catch (error) {
          if (!stopped) {stopped = true; controller.error(error);}
          await close();
        }
      },
      async cancel() {stopped = true; await close();},
    });
    return new Response(stream, {status, headers});
  } catch (error) { await handle.close(); throw error; }
}
