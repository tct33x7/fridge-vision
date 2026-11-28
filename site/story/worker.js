// 思考记录这一页的小后台：保存和读取每一段下面的"备注"。
//
// GET    /api/notes        任何人都能读，返回全部备注
// POST   /api/notes        任何人都能写：只收文字，最多 300 个字，同一个网络地址 10 分钟最多 5 条
// DELETE /api/notes/<id>   只有带专用链接里那串字（请求头 x-edit-key）才能删
// 其余的地址都交给静态文件（public/ 里的网页）。
//
// 备注存在 KV 里的一个键 "notes" 下，是一个数组：[{id, slot, text, at}]。
// 不存写备注的人的网络地址；限速用的是地址加盐以后的哈希，10 分钟后自动过期。
// 想把"任何人都能写"关掉：在 wrangler.jsonc 里加 "vars": {"NOTES_OPEN": "false"} 再发布，
// 之后只有带专用链接的人能写。

const MAX_CHARS = 300;     // 一条备注最多多少个字
const MAX_NOTES = 500;     // 一共最多多少条
const MAX_PER_SLOT = 60;   // 每一段最多多少条
const RATE_MAX = 5;        // 同一个地址在一个时间窗里最多几条
const RATE_WINDOW = 600;   // 时间窗，秒
// 每一段的名字，要和 public/index.html 里的 data-slot 一一对上。名字按内容起，不按顺序编号：
// 以后在中间加一段，原来各段下面的备注不会错位。
const SLOTS = new Set([
  "start", "watch", "line", "doubt", "measure", "above", "inside", "check",
  "posd", "cabinet", "hand", "name", "cost", "twocam", "three", "reuse", "done",
  "look-back", "ai-how", "ai-think", "now",
]);

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

async function loadNotes(env) {
  const raw = await env.NOTES.get("notes");
  if (!raw) return [];
  try {
    const list = JSON.parse(raw);
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function sameKey(given, expected) {
  if (!expected || !given) return false;
  const a = new TextEncoder().encode(given);
  const b = new TextEncoder().encode(expected);
  if (a.byteLength !== b.byteLength) return false;
  return crypto.subtle.timingSafeEqual(a, b);
}

function isOwner(request, env) {
  return sameKey(request.headers.get("x-edit-key") || "", env.EDIT_KEY || "");
}

// 只留文字：去掉控制字符和看不见的排版字符，换行最多连着两个。
function cleanText(value) {
  return value
    .replace(/\r\n?/g, "\n")
    .replace(/[\u0000-\u0009\u000B-\u001F\u007F-\u009F​-‏‪-‮⁦-⁩﻿]/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

async function rateKey(request, env) {
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const data = new TextEncoder().encode((env.EDIT_KEY || "salt") + "|" + ip);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", data));
  let hex = "";
  for (let i = 0; i < 8; i++) hex += digest[i].toString(16).padStart(2, "0");
  return "rl:" + hex;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/notes") {
      if (request.method === "GET") return json(await loadNotes(env));
      if (request.method !== "POST") return json({ error: "method" }, 405);
      const owner = isOwner(request, env);
      if (env.NOTES_OPEN === "false" && !owner) return json({ error: "closed" }, 403);
      let body;
      try {
        body = await request.json();
      } catch {
        return json({ error: "bad json" }, 400);
      }
      if (!body || typeof body !== "object") return json({ error: "bad json" }, 400);
      if (typeof body.website === "string" && body.website !== "") return json({ error: "rejected" }, 400);
      if (!SLOTS.has(body.slot)) return json({ error: "slot" }, 400);
      const text = typeof body.text === "string" ? cleanText(body.text) : "";
      if (!text) return json({ error: "empty" }, 400);
      if (Array.from(text).length > MAX_CHARS) return json({ error: "too long" }, 413);

      let rk = null;
      let used = 0;
      if (!owner) {
        rk = await rateKey(request, env);
        used = parseInt((await env.NOTES.get(rk)) || "0", 10) || 0;
        if (used >= RATE_MAX) return json({ error: "too fast" }, 429);
      }

      const notes = await loadNotes(env);
      if (notes.length >= MAX_NOTES) return json({ error: "full" }, 409);
      if (notes.filter((n) => n.slot === body.slot).length >= MAX_PER_SLOT) return json({ error: "full" }, 409);
      const note = { id: crypto.randomUUID(), slot: body.slot, text, at: new Date().toISOString() };
      notes.push(note);
      await env.NOTES.put("notes", JSON.stringify(notes));
      if (rk) await env.NOTES.put(rk, String(used + 1), { expirationTtl: RATE_WINDOW });
      return json(note, 201);
    }

    const one = url.pathname.match(/^\/api\/notes\/([0-9a-f-]{36})$/);
    if (one) {
      if (request.method !== "DELETE") return json({ error: "method" }, 405);
      if (!isOwner(request, env)) return json({ error: "forbidden" }, 403);
      const notes = await loadNotes(env);
      const left = notes.filter((n) => n.id !== one[1]);
      if (left.length === notes.length) return json({ error: "not found" }, 404);
      await env.NOTES.put("notes", JSON.stringify(left));
      return json({ ok: true });
    }

    if (url.pathname.startsWith("/api/")) return json({ error: "not found" }, 404);
    return env.ASSETS.fetch(request);
  },
};
