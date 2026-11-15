// Names the repository a ghost belongs to.
import { gitOut } from "../merge.ts";
import { repoKey } from "./model.ts";

/** The key and the current branch of the repository holding `cwd`. */
export async function currentRepo(cwd: string): Promise<{ key: string; branch: string }> {
	const toplevel = await gitOut(cwd, "rev-parse", "--show-toplevel").catch(() => {
		throw new Error("Ghosts belong to a git repository, and this directory is not in one.");
	});
	return { key: repoKey(toplevel), branch: await gitOut(toplevel, "branch", "--show-current") };
}
