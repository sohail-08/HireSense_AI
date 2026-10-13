import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/interviews/interviewSchedule.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
});
const { buildInterviewSchedule } = await import("data:text/javascript;base64," + Buffer.from(outputText).toString("base64"));

test("invitations and reschedules use sequential slots in Dhaka without extra controls", () => {
  const fields = { date: "2030-10-15", start_time: "10:00", duration_minutes: "30", buffer_minutes: "10", instructions: "Bring your laptop.", reason: "Time changed" };
  const payload = buildInterviewSchedule(fields);
  assert.equal(payload.mode, "sequential");
  assert.equal(payload.timezone, "Asia/Dhaka");
  assert.equal(payload.duration_minutes, 30);
  assert.equal(payload.buffer_minutes, 10);
  assert.equal(payload.date, fields.date);
  assert.equal(payload.instructions, fields.instructions);
  assert.equal(payload.reason, fields.reason);
  assert.equal(fields.duration_minutes, "30");
});

test("stale hidden mode and zone values cannot override current UI defaults", () => {
  const payload = buildInterviewSchedule({ duration_minutes: "45", buffer_minutes: "0", mode: "shared", timezone: "Europe/London" });
  assert.equal(payload.mode, "sequential");
  assert.equal(payload.timezone, "Asia/Dhaka");
  assert.equal(payload.buffer_minutes, 0);
});
