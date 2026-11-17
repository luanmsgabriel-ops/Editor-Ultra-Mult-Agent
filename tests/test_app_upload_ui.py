"""Run the actual studio transfer functions in Node, with a bounded host/HTTP peer.

This does not claim browser or tablet coverage. File/Blob, async functions and
the studio's save/reconcile/import code are real; only DOM painting and the
external transport are replaced. The peer records every POST and durable asset
so lost-response tests can detect duplicate transfers and false receipts.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


UI = Path(__file__).parents[1] / "editor_ultra_app" / "ui.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required for studio JavaScript checks")


BOOT = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');
const html = fs.readFileSync(process.argv[2], 'utf8');
const context = vm.createContext({assert, URL, File, Blob, AbortController,
    crypto: webcrypto, setTimeout, clearTimeout, TextEncoder});
function extract(start, end) {
    const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
    assert.ok(a >= 0 && b > a, 'studio function boundaries are present');
    return html.slice(a, b);
}
"""


SETUP = r"""
const origin = 'https://editor.example';
const conn = {ready: true, mode: 'openai', projectId: 'project-one', revision: 1,
    jobs: [], uncertain: false, busy: 'Uploading',
    uploadCapabilities: {direct: true, origin, max_bytes: 536870912}};
const blobs = new Map(), remoteAssets = new Map(), previewURLs = new Map();
const byId = new Map(), features = [];
let draftSeq = 1, savedSeq = 0, saveTail = Promise.resolve(), saveTimer = null;
let state, mode = 'success', receiptVariant = null, externalEditAfterCommit = false;
const counts = {posts: 0, reads: 0, saves: 0, authorizations: 0};
const phases = [], logs = [], tickets = new Map();
const uid = () => crypto.randomUUID();
function blank() {
    return {schema: 'editor-ultra-interface/1', id: 'project-one', name: 'Test',
        revision: 1, sourceRev: 1, editRev: 1, sourceType: 'video', mode: 'ready',
        ratio: '9:16', targetDuration: 30, preserve: [], comments: [], history: [],
        assets: {ref: [], footage: [], identity: [], narration: [], logo: [], clone: [], result: []},
        shots: [{id: 'shot-one', seconds: 8, in: 0, out: 8, files: [], rev: 1},
                {id: 'shot-two', seconds: 8, in: 0, out: 8, files: [], rev: 1}]};
}
function clone(value) { return JSON.parse(JSON.stringify(value)); }
const peer = {project_id: conn.projectId, revision: 1, state: blank(), assets: []};
function snapshot() { return clone(peer); }
function safeURL(value) { return typeof value === 'string' ? value : ''; }
function $() { return {innerHTML: '', textContent: '', classList: {toggle() {}}}; }
function $$() { return []; }
function renderConnection() {}
function render() { phases.push([...transfers.values()].map(t => t.phase)); }
function locks() {}
function updateProjects() {}
function reconcileJob() {}
function rememberNavigation() {}
function setCatalog() {}
function jobBusy() { return false; }
function log(message) { logs.push(message); }
function note() {}
function esc(value) { return String(value); }
function putReceipt(record, item) {
    record.assets.push(item);
    if (item.role === 'shot') record.state.shots.find(s => s.id === item.shot_id).files.push(item);
    else record.state.assets[item.role].push(item);
}
function readResponse() {
    const response = snapshot();
    if (receiptVariant) {
        // A same-name/same-size asset must never stand in for the exact receipt.
        const item = {id: 'unrelated-asset', name: originalFile.name, type: originalFile.type,
            size: originalFile.size, role: entry.role, shot_id: entry.shot_id,
            hostFileId: 'direct:' + local.uploadId, sha256: 'peer-fixture-digest'};
        if (receiptVariant === 'uuid') item.hostFileId = 'direct:' + uid();
        if (receiptVariant === 'role') item.role = 'footage';
        if (receiptVariant === 'shot') item.shot_id = 'shot-two';
        putReceipt(response, item);
        if (receiptVariant === 'project') response.project_id = 'another-project';
        if (receiptVariant === 'duplicate') putReceipt(response, {...item, id: 'second-match'});
        if (receiptVariant === 'unlinked') response.state.assets[item.role] = [];
    }
    return response;
}
async function hostCall(name, args) {
    if (name === 'editor_get_project') {
        counts.reads++;
        if (mode === 'read-fails') throw new Error('host temporarily unavailable');
        assert.equal(args.project_id, peer.project_id);
        return {structuredContent: readResponse()};
    }
    assert.equal(name, 'editor_save_project');
    assert.equal(args.project_id, peer.project_id);
    assert.equal(args.expected_revision, peer.revision);
    if (args.state.ui_action === 'begin_upload') {
        counts.authorizations++;
        const request = args.state.upload_request;
        tickets.set(request.upload_id, clone(request));
        return {structuredContent: {status: 'authorized', project_id: peer.project_id,
            revision: peer.revision, upload_id: request.upload_id},
            _meta: {editor: {upload: {upload_id: request.upload_id, method: 'POST',
                url: origin + '/upload-tickets/' + request.upload_id,
                expires_at: Date.now() + 300000, max_bytes: request.size_bytes,
                headers: {'Authorization': 'Upload test-ticket-012345678901234567890',
                          'Content-Type': request.mime_type}}}}};
    }
    counts.saves++;
    const incoming = clone(args.state), known = new Map(peer.assets.map(a => [a.id, a]));
    for (const [role, items] of Object.entries(incoming.assets)) incoming.assets[role] = items.map(a => known.get(a.id)).filter(Boolean);
    for (const shot of incoming.shots) shot.files = shot.files.map(a => known.get(a.id)).filter(Boolean);
    peer.state = incoming;
    peer.revision++;
    peer.state.revision = peer.revision;
    return {structuredContent: snapshot()};
}
const window = {openai: {callTool: hostCall}};
async function fetch(url, options) {
    counts.posts++;
    const id = new URL(url).pathname.split('/').at(-1), ticket = tickets.get(id);
    assert.ok(ticket, 'binary request has an issued ticket');
    assert.equal(options.method, 'POST');
    assert.equal(options.body, originalFile, 'the original File is transmitted unchanged');
    assert.equal(options.credentials, 'omit');
    assert.equal(options.redirect, 'error');
    if (mode === 'invalid') return {ok: false, status: 422,
        json: async () => ({code: 'invalid_media', error: '/private/path SECRET', uncertain: false})};
    if (mode === 'legacy') return {ok: false, status: 409,
        json: async () => ({code: 'upload_failed', error: 'revision maybe? SECRET'})};
    if (mode === 'html-error') return {ok: false, status: 409,
        json: async () => { throw new SyntaxError('Unexpected HTML'); }};
    if (mode === 'network' || mode === 'read-fails') throw new TypeError('Failed to fetch');
    assert.ok(!peer.assets.some(a => a.hostFileId === 'direct:' + id), 'no duplicate binary import');
    const item = {id: 'received-' + counts.posts, name: ticket.file_name, type: ticket.mime_type,
        size: ticket.size_bytes, role: ticket.role, shot_id: ticket.shot_id,
        hostFileId: 'direct:' + id, sha256: 'peer-fixture-digest'};
    putReceipt(peer, item);
    peer.revision++;
    peer.state.revision = peer.revision;
    if (externalEditAfterCommit) {
        // Another authenticated session edits the same project after admission,
        // before this UI learns whether its POST succeeded.
        peer.state.objective = 'Objetivo atualizado em outra sessão';
        peer.state.name = 'Nome atualizado em outra sessão';
        peer.revision++;
        peer.state.revision = peer.revision;
    }
    if (mode === 'lost-network') throw new TypeError('response lost after commit');
    if (mode === 'lost-json') return {ok: true, status: 200,
        json: async () => { throw new SyntaxError('truncated successful response'); }};
    return {ok: true, status: 200, json: async () => ({...snapshot(), asset_id: item.id, asset: item})};
}
"""


BOUNDARIES = [
    ("function unwrap(", "async function fingerprint("),
    ("function approvalRecord(", "function updateProjects("),
    ("function applyServer(", "function rememberNavigation("),
    ("function serializableState(", "function scheduleSave("),
    ("async function refreshProject(", "function showServerRequest("),
    ("function normalize(", "// Business data comes from the server"),
    ("function allAssets(", "function cloneOK("),
]


FIXTURE = r"""
state = blank();
const originalFile = new File([new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112, 1, 2, 3, 4])],
    '148379.mp4', {type: 'video/mp4', lastModified: 12345});
const selected = {id: 'local-selection', name: originalFile.name, type: originalFile.type,
    size: originalFile.size, lastModified: originalFile.lastModified};
const local = {file: originalFile, url: 'blob:local-preview'};
blobs.set(selected.id, local);
state.assets.ref.push(selected);
let entry = {role: 'ref', asset: selected};
function asShot() {
    state.assets.ref = [];
    state.shots[0].files.push(selected);
    entry = {role: 'shot', shot_id: 'shot-one', asset: selected};
}
async function authorizeSelected() {
    const uploadId = uploadIdentifier(selected, local);
    const authorization = await requestUploadAuthorization({project_id: conn.projectId,
        expected_revision: conn.revision, role: entry.role, shot_id: entry.shot_id,
        upload_id: uploadId, file_name: originalFile.name, mime_type: originalFile.type,
        size_bytes: originalFile.size});
    return {uploadId, authorization};
}
"""


def run_ui(script: str):
    code = BOOT
    code += f"\nvm.runInContext({json.dumps(SETUP)}, context);\n"
    code += f"for (const [a,b] of {json.dumps(BOUNDARIES)}) vm.runInContext(extract(a,b), context);\n"
    code += f"vm.runInContext({json.dumps(FIXTURE)}, context);\n"
    code += f"Promise.resolve(vm.runInContext({json.dumps('(async () => {' + script + '})()')}, context))"
    code += ".catch(error => { console.error(error); process.exitCode = 1; });\n"
    result = subprocess.run([NODE, "-", str(UI)], input=code, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("status,code,expected,uncertain", [
    (422, "invalid_media", "conteúdo deste arquivo", False),
    (422, "media_duration", "até 10 minutos", False),
    (422, "video_stream", "mais de uma faixa", False),
    (409, "revision_conflict", "revisão do projeto", True),
    (409, "upload_in_progress", "ainda está sendo recebido", True),
    (409, "upload_failed", "verificação deste envio", True),
    (500, "upload_uncertain", "resposta do envio", True),
])
def test_upload_errors_use_codes_without_exposing_server_details(status, code, expected, uncertain):
    run_ui(rf"""
    const error = uploadHTTPError({status}, {{code: {json.dumps(code)},
        error: '/data/private SECRET <script>alert(1)</script>', uncertain: false}});
    assert.ok(error.message.toLowerCase().includes({json.dumps(expected)}));
    assert.equal(error.code, {json.dumps(code)});
    assert.equal(error.uncertain, {json.dumps(uncertain)});
    assert.equal(error.uploadKnownFailure, {json.dumps(not uncertain)});
    assert.ok(!/SECRET|script|\/data\//.test(error.message));
    """)


def test_unknown_409_is_not_a_claim_that_project_changed():
    run_ui(r"""
    for (const body of [null, {}, {code: 'proxy_future_error'}, {code: '<script>'},
                        {code: 'upload_failed', error: 'The project changed'}]) {
        const error = uploadHTTPError(409, body);
        assert.equal(error.uncertain, true);
        assert.equal(error.uploadKnownFailure, false);
        assert.ok(!/projeto mudou|revisão do projeto/i.test(error.message));
    }
    const maybeCommitted = uploadHTTPError(422, {code: 'invalid_media', uncertain: true});
    assert.equal(maybeCommitted.uncertain, true, 'explicit uncertainty must win over a known code');
    """)


def test_binary_post_reads_validation_response_and_keeps_file_selected():
    run_ui(r"""
    mode = 'invalid';
    await assert.rejects(importPending(), error => error.code === 'invalid_media' && !error.uncertain);
    assert.equal(counts.posts, 1);
    assert.equal(counts.reads, 0, 'known rejection needs no speculative receipt query');
    assert.equal(peer.assets.length, 0);
    assert.equal(blobs.get(selected.id).file, originalFile);
    assert.equal(pendingLocal().length, 1);
    assert.equal(transfers.get(selected.id).phase, 'error');
    assert.ok(!transfers.get(selected.id).error.includes('SECRET'));
    assert.equal(uploadControllers.size, 0);
    const sameId = local.uploadId;
    mode = 'success';
    await importPending();
    assert.equal(local.uploadId, sameId, 'explicit retry keeps the upload identity');
    assert.equal(peer.assets.length, 1);
    assert.equal(counts.posts, 2, 'only the explicit user retry sends bytes again');
    """)


@pytest.mark.parametrize("mode", ["legacy", "html-error", "network", "read-fails"])
def test_uncertain_failure_reads_once_and_does_not_resend(mode):
    run_ui(f"""
    mode = {json.dumps(mode)};
    await assert.rejects(importPending(), error => error.uncertain === true);
    assert.equal(counts.posts, 1);
    assert.equal(counts.authorizations, 1);
    assert.equal(counts.reads, 1);
    assert.equal(peer.assets.length, 0);
    assert.equal(blobs.get(selected.id).file, originalFile);
    assert.equal(pendingLocal().length, 1);
    assert.equal(transfers.get(selected.id).phase, 'uncertain');
    assert.ok(local.uploadId);
    assert.equal(uploadControllers.size, 0);
    """)


@pytest.mark.parametrize("mode", ["lost-network", "lost-json"])
def test_committed_upload_with_lost_response_is_recovered_without_duplicate(mode):
    run_ui(f"""
    mode = {json.dumps(mode)};
    await importPending();
    assert.equal(counts.posts, 1);
    assert.equal(counts.authorizations, 1);
    assert.equal(counts.reads, 1);
    assert.equal(peer.assets.length, 1);
    assert.equal(state.assets.ref.length, 1);
    assert.equal(state.assets.ref[0].id, peer.assets[0].id);
    assert.equal(blobs.get(peer.assets[0].id).file, originalFile);
    assert.equal(pendingLocal().length, 0);
    assert.equal(transfers.get(peer.assets[0].id).phase, 'received');
    assert.equal(uploadControllers.size, 0);
    await importPending();
    assert.equal(counts.posts, 1, 'a later import also respects the recovered receipt');
    """)


@pytest.mark.parametrize("variant", ["uuid", "role", "shot", "project", "duplicate", "unlinked"])
def test_recovery_requires_one_exact_project_role_shot_and_linked_receipt(variant):
    run_ui(f"""
    if ({json.dumps(variant)} === 'shot') asShot();
    mode = 'network'; receiptVariant = {json.dumps(variant)};
    await assert.rejects(importPending(), error => error.uncertain === true);
    assert.equal(counts.posts, 1);
    assert.equal(counts.reads, 1);
    assert.equal(counts.authorizations, 1);
    assert.equal(blobs.get(selected.id).file, originalFile);
    assert.equal(pendingLocal().length, 1, 'unrelated or unlinked receipt does not admit selected media');
    assert.equal(transfers.get(selected.id).phase, 'uncertain');
    """)


def test_queued_imports_share_the_received_asset_and_send_bytes_once():
    run_ui(r"""
    await Promise.all([importPending(), importPending()]);
    assert.equal(counts.posts, 1);
    assert.equal(counts.authorizations, 1);
    assert.equal(counts.reads, 0);
    assert.equal(peer.assets.length, 1);
    assert.equal(state.assets.ref.length, 1);
    assert.equal(blobs.get(peer.assets[0].id).file, originalFile);
    assert.equal(pendingLocal().length, 0);
    """)


def test_lost_response_recovery_preserves_external_edit_before_final_save():
    run_ui(r"""
    state.objective = 'Objetivo local anterior';
    state.name = 'Nome local anterior';
    mode = 'lost-network'; externalEditAfterCommit = true;
    await importPending();
    assert.equal(counts.posts, 1);
    assert.equal(counts.reads, 1);
    assert.equal(counts.saves, 2, 'initial selections and final receipt synchronization only');
    assert.equal(conn.revision, 5, 'save, file admission, external edit and final save each advance once');
    assert.equal(peer.revision, 5);
    assert.equal(state.objective, 'Objetivo atualizado em outra sessão');
    assert.equal(peer.state.objective, 'Objetivo atualizado em outra sessão');
    assert.equal(state.name, 'Nome atualizado em outra sessão');
    assert.equal(peer.state.name, 'Nome atualizado em outra sessão');
    assert.equal(peer.assets.length, 1);
    assert.equal(state.assets.ref[0].id, peer.assets[0].id);
    assert.equal(blobs.get(peer.assets[0].id).file, originalFile);
    assert.equal(pendingLocal().length, 0);
    """)
