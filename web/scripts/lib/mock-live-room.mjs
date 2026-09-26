/**
 * A synthetic co-editing room for MOCKED browser proofs (RADD-1397): the smallest server that
 * speaks what the collab remote's y-websocket provider does, over a hand-rolled RFC 6455 socket
 * (the toolchain has no `ws`), with one fake peer already in the room.
 *
 * It is the protocol, not the product: no auth, no persistence, no observer filter, no seed grant
 * beyond "the document is empty". Its job is to let a browser prove the CLIENT — that the remote
 * joins, binds the host's editor, sees a colleague and saves — without a real instance.
 */
import { createHash } from "node:crypto";
import * as Y from "yjs";
import * as syncProtocol from "y-protocols/sync";
import * as awarenessProtocol from "y-protocols/awareness";
import * as encoding from "lib0/encoding";
import * as decoding from "lib0/decoding";

const MESSAGE_SYNC = 0;
const MESSAGE_AWARENESS = 1;
const MESSAGE_QUERY_AWARENESS = 3;
const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
export const FRAGMENT = "prosemirror";

function frame(payload, opcode = 0x2) {
  const length = payload.length;
  let header;
  if (length < 126) header = Buffer.from([0x80 | opcode, length]);
  else if (length < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x80 | opcode; header[1] = 126; header.writeUInt16BE(length, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x80 | opcode; header[1] = 127; header.writeBigUInt64BE(BigInt(length), 2);
  }
  return Buffer.concat([header, Buffer.from(payload)]);
}

/** Split complete client frames off `buffer` (clients always mask). */
function readFrames(buffer) {
  const frames = [];
  let offset = 0;
  for (;;) {
    if (buffer.length - offset < 2) break;
    const opcode = buffer[offset] & 0x0f;
    let length = buffer[offset + 1] & 0x7f;
    let cursor = offset + 2;
    if (length === 126) { if (buffer.length - cursor < 2) break; length = buffer.readUInt16BE(cursor); cursor += 2; }
    else if (length === 127) { if (buffer.length - cursor < 8) break; length = Number(buffer.readBigUInt64BE(cursor)); cursor += 8; }
    if (buffer.length - cursor < 4 + length) break;
    const mask = buffer.subarray(cursor, cursor + 4);
    cursor += 4;
    const payload = Buffer.from(buffer.subarray(cursor, cursor + length));
    for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
    frames.push({ opcode, payload });
    offset = cursor + length;
  }
  return { frames, rest: buffer.subarray(offset) };
}

/**
 * `peer` is the colleague already editing: an awareness state with a client id higher than any a
 * browser draws in practice, so the browser is always the elected saver.
 */
export function createMockLiveRoom({ peer }) {
  const doc = new Y.Doc();
  doc.clientID = 0xfffffff0;
  const awareness = new awarenessProtocol.Awareness(doc);
  awareness.setLocalState({ user: peer, role: "editor" });
  const connections = new Set();
  const upgrades = [];

  const send = (connection, bytes) => { if (!connection.closed) connection.socket.write(frame(bytes)); };
  const awarenessFrame = (clients) => {
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, MESSAGE_AWARENESS);
    encoding.writeVarUint8Array(encoder, awarenessProtocol.encodeAwarenessUpdate(awareness, clients));
    return encoding.toUint8Array(encoder);
  };
  doc.on("update", (update, origin) => {
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, MESSAGE_SYNC);
    syncProtocol.writeUpdate(encoder, update);
    const bytes = encoding.toUint8Array(encoder);
    for (const connection of connections) if (connection !== origin) send(connection, bytes);
  });
  awareness.on("update", ({ added, updated, removed }, origin) => {
    // A socket controls the clients it ADDED (y-websocket's server rule): a provider also echoes
    // everyone else's states, and those must not leave with it.
    if (origin?.clients) {
      for (const id of added) origin.clients.add(id);
      for (const id of removed) origin.clients.delete(id);
    }
    const bytes = awarenessFrame([...added, ...updated, ...removed]);
    for (const connection of connections) if (connection !== origin) send(connection, bytes);
  });

  function receive(connection, data) {
    const decoder = decoding.createDecoder(data);
    const encoder = encoding.createEncoder();
    const type = decoding.readVarUint(decoder);
    if (type === MESSAGE_SYNC) {
      encoding.writeVarUint(encoder, MESSAGE_SYNC);
      syncProtocol.readSyncMessage(decoder, encoder, doc, connection);
      if (encoding.length(encoder) > 1) send(connection, encoding.toUint8Array(encoder));
    } else if (type === MESSAGE_AWARENESS) {
      awarenessProtocol.applyAwarenessUpdate(awareness, decoding.readVarUint8Array(decoder), connection);
    } else if (type === MESSAGE_QUERY_AWARENESS) {
      send(connection, awarenessFrame([...awareness.getStates().keys()]));
    }
  }

  /** Accept an HTTP upgrade (the server's `upgrade` event). */
  function upgrade(req, socket) {
    upgrades.push(req.url);
    const accept = createHash("sha1").update(req.headers["sec-websocket-key"] + WS_GUID).digest("base64");
    socket.write(["HTTP/1.1 101 Switching Protocols", "Upgrade: websocket", "Connection: Upgrade",
      `Sec-WebSocket-Accept: ${accept}`, "", ""].join("\r\n"));
    const connection = { socket, closed: false, clients: new Set() };
    connections.add(connection);
    let pending = Buffer.alloc(0);
    const close = () => {
      if (connection.closed) return;
      connection.closed = true;
      connections.delete(connection);
      awarenessProtocol.removeAwarenessStates(awareness, [...connection.clients], null);
      socket.destroy();
    };
    socket.on("data", (chunk) => {
      const { frames, rest } = readFrames(Buffer.concat([pending, chunk]));
      pending = rest;
      for (const { opcode, payload } of frames) {
        if (opcode === 0x8) { if (!connection.closed) socket.write(frame(payload.subarray(0, 2), 0x8)); close(); return; }
        if (opcode === 0x9) { socket.write(frame(payload, 0xa)); continue; }
        if (opcode === 0x2 || opcode === 0x1) receive(connection, new Uint8Array(payload));
      }
    });
    socket.on("close", close);
    socket.on("error", close);
    // The server speaks first: its state vector, then everyone already here.
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, MESSAGE_SYNC);
    syncProtocol.writeSyncStep1(encoder, doc);
    send(connection, encoding.toUint8Array(encoder));
    send(connection, awarenessFrame([...awareness.getStates().keys()]));
  }

  return {
    doc,
    awareness,
    upgrade,
    upgrades,
    /** Open sockets right now. */
    get open() { return connections.size; },
    /** Whether a joiner should seed: the shared document is still empty. */
    get empty() { return doc.getXmlFragment(FRAGMENT).length === 0; },
    /** The colleague types a paragraph of their own. */
    peerWrites(text) {
      doc.transact(() => {
        const paragraph = new Y.XmlElement("paragraph");
        paragraph.insert(0, [new Y.XmlText(text)]);
        doc.getXmlFragment(FRAGMENT).push([paragraph]);
      });
    },
    close() {
      for (const connection of [...connections]) connection.socket.destroy();
      awareness.destroy();
      doc.destroy();
    },
  };
}
