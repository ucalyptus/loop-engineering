/**
 * loopctl as an agent-harness extension, for pi (@earendil-works/pi-coding-agent) and oh-my-pi.
 *
 * Inside the harness, the harness's own agent is the actuator and the project's loop.toml is the
 * setpoint. When the agent tries to finish, this runs `loopctl check`: every check, plus every
 * admission gate, on the uncommitted work. If anything fails, the agent is sent back with the
 * failing output instead of stopping.
 *
 *   oh-my-pi  session_stop         -> { decision: "block", reason }
 *   pi        agent_before_settle  -> { entries: [custom_message], continue: true }
 *
 * Governor: after LOOPCTL_MAX_ROUNDS forced rounds (default 5), or when the same things fail
 * 3 rounds in a row, the agent may stop and the user is told why.
 *
 * Load:     pi -e integrations/loopctl.ts      omp -e integrations/loopctl.ts
 *   or copy it into .pi/extensions/ (pi) or .omp/extensions/ (oh-my-pi) of a project.
 * Manifest: ./loop.toml in the session's directory, or $LOOPCTL_MANIFEST.
 * Command:  /loop shows checks and gates now; /loop off and /loop on toggle the stop gate.
 */
import { existsSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), ".."); // repo root, for `python3 -m loopctl`
const MAX_ROUNDS = Number(process.env.LOOPCTL_MAX_ROUNDS ?? 5);
const STALL_ROUNDS = 3;
const TAIL = 1500;

type Gate = { name: string; ok: boolean; detail: string };
type CheckResult = {
	ok: boolean;
	passing: string[];
	failing: string[];
	output: Record<string, string>;
	admission: Gate[];
	changed_lines: number;
};

// The part of ExtensionAPI this uses; pi and oh-my-pi both provide it.
type Ctx = { cwd: string; ui: { notify(message: string, level?: "info" | "warning" | "error"): void } };
type Api = {
	exec(cmd: string, args: string[], opts?: { cwd?: string; timeout?: number }): Promise<{ stdout: string; stderr: string; code: number }>;
	on(event: string, handler: (event: unknown, ctx: Ctx) => unknown): unknown;
	registerCommand(name: string, spec: { description: string; handler: (args: string, ctx: Ctx) => Promise<void> }): void;
};

export default function loopctl(pi: Api) {
	let enabled = true;
	let rounds = 0;
	let lastSignature = "";
	let sameRounds = 0;

	const manifestIn = (cwd: string) => {
		const m = process.env.LOOPCTL_MANIFEST ?? "loop.toml";
		return isAbsolute(m) ? m : join(cwd, m);
	};

	async function check(cwd: string): Promise<CheckResult | undefined> {
		const manifest = manifestIn(cwd);
		if (!existsSync(manifest)) return undefined;
		const pythonPath = [ROOT, process.env.PYTHONPATH].filter(Boolean).join(":");
		const r = await pi.exec("env", [`PYTHONPATH=${pythonPath}`, "python3", "-m", "loopctl", "check", manifest, "--json"], {
			cwd,
			timeout: 600_000,
		});
		try {
			return JSON.parse(r.stdout) as CheckResult;
		} catch {
			throw new Error(`loopctl check failed (exit ${r.code}): ${(r.stderr || r.stdout).trim()}`);
		}
	}

	function summary(r: CheckResult): string {
		const checks = [...r.passing.map(n => `✓ ${n}`), ...r.failing.map(n => `✗ ${n}`)];
		const gates = r.admission.map(g => `${g.ok ? "✓" : "✗"} admission[${g.name}]`);
		return [...checks, ...gates].join("  ");
	}

	function feedback(r: CheckResult, manifest: string): string {
		const lines = [
			`loopctl: not done yet (round ${rounds} of ${MAX_ROUNDS}). Done means every check in loop.toml passes and every admission gate accepts your uncommitted changes.`,
		];
		for (const name of r.failing) lines.push(`\nFailing check \`${name}\`:\n${(r.output[name] ?? "").slice(-TAIL)}`);
		for (const g of r.admission.filter(g => !g.ok)) {
			lines.push(`\nRejected by admission gate \`${g.name}\`: ${g.detail}. Undo the change it guards against; do not edit the gate or the checks.`);
		}
		lines.push(`\nFix these, then finish again. Check yourself with: PYTHONPATH=${ROOT} python3 -m loopctl check ${manifest}`);
		return lines.join("\n");
	}

	function resetGovernor() {
		rounds = 0;
		sameRounds = 0;
		lastSignature = "";
	}

	/** The comparator: undefined lets the agent stop; a string sends it back with that feedback. */
	async function gate(ctx: Ctx): Promise<string | undefined> {
		if (!enabled) return undefined;
		let r: CheckResult | undefined;
		try {
			r = await check(ctx.cwd);
		} catch (e) {
			ctx.ui.notify(String(e), "error");
			return undefined; // a broken sensor must not trap the agent
		}
		if (!r) return undefined; // no loop.toml here: nothing to enforce
		if (r.ok) {
			if (rounds) ctx.ui.notify(`loopctl: converged after ${rounds} extra round(s). ${summary(r)}`, "info");
			resetGovernor();
			return undefined;
		}
		const signature = JSON.stringify([r.failing, r.admission.filter(g => !g.ok).map(g => g.name)]);
		sameRounds = signature === lastSignature ? sameRounds + 1 : 1;
		lastSignature = signature;
		if (rounds >= MAX_ROUNDS || sameRounds > STALL_ROUNDS) {
			const why = rounds >= MAX_ROUNDS ? `budget of ${MAX_ROUNDS} rounds spent` : `no progress in ${STALL_ROUNDS} rounds`;
			ctx.ui.notify(`loopctl: letting the agent stop (${why}); still failing. ${summary(r)}`, "warning");
			resetGovernor();
			return undefined;
		}
		rounds++;
		ctx.ui.notify(`loopctl: sending the agent back (round ${rounds}). ${summary(r)}`, "warning");
		return feedback(r, manifestIn(ctx.cwd));
	}

	// oh-my-pi: refuse to finish until the checks pass.
	pi.on("session_stop", async (_event, ctx) => {
		const reason = await gate(ctx);
		return reason ? { decision: "block", reason } : undefined;
	});

	// pi: at the final boundary, add the feedback and ask for one more model turn. Only a run that
	// completed (not aborted with Esc, not an error) is sent back. The event's context.canContinue
	// reads false at a normal finish; pi recomputes it after this custom_message entry is added.
	pi.on("agent_before_settle", async (event, ctx) => {
		if (!event || typeof event !== "object" || !("outcome" in event) || event.outcome !== "completed") return undefined;
		const reason = await gate(ctx);
		return reason
			? { entries: [{ type: "custom_message", customType: "loopctl", content: reason, display: true }], continue: true }
			: undefined;
	});

	pi.registerCommand("loop", {
		description: "loopctl: show checks and admission gates for ./loop.toml; /loop off or /loop on toggles the stop gate",
		handler: async (args, ctx) => {
			const arg = args.trim();
			if (arg === "off" || arg === "on") {
				enabled = arg === "on";
				resetGovernor();
				ctx.ui.notify(`loopctl stop gate ${arg}`, "info");
				return;
			}
			const r = await check(ctx.cwd);
			ctx.ui.notify(r ? `${r.ok ? "converged" : "not converged"}: ${summary(r)}` : `no loop.toml in ${ctx.cwd}`, r?.ok ? "info" : "warning");
		},
	});
}
