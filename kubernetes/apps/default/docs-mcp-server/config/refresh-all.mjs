import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const workerUrl = process.env.WORKER_URL;

if (!workerUrl) {
  throw new Error("WORKER_URL is required");
}

const cli = ["--enable-source-maps", "/app/dist/index.js"];
const require = createRequire("/app/package.json");
const { createTRPCProxyClient, httpBatchLink } = require("@trpc/client");
const superjson = require("superjson").default;
const terminalStatuses = new Set(["completed", "failed", "cancelled"]);

function run(args, captureOutput = false) {
  return spawnSync(process.execPath, [...cli, ...args], {
    encoding: "utf8",
    env: process.env,
    stdio: captureOutput ? ["ignore", "pipe", "inherit"] : "inherit",
  });
}

function createWorkerClient() {
  return createTRPCProxyClient({
    links: [
      httpBatchLink({
        url: workerUrl,
        transformer: superjson,
      }),
    ],
  });
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function errorMessage(error) {
  if (error instanceof Error) {
    return error.message;
  }

  if (typeof error === "string") {
    return error;
  }

  return JSON.stringify(error) || "unknown error";
}

async function refresh(client, library, version) {
  const label = library + "@" + (version || "latest");
  console.log("Refreshing " + label);

  const { jobId } = await client.enqueueRefreshJob.mutate({
    library,
    version: version || null,
  });

  for (;;) {
    const job = await client.getJob.query({ id: jobId });

    if (!job) {
      throw new Error("Worker returned no job for " + label);
    }

    if (!terminalStatuses.has(job.status)) {
      await sleep(2000);
      continue;
    }

    if (job.status === "completed") {
      return;
    }

    throw new Error(
      "Refresh " + job.status + " for " + label + ": " + errorMessage(job.error),
    );
  }
}

const listResult = run(
  ["list", "--server-url", workerUrl, "--output", "json", "--quiet"],
  true,
);

if (listResult.status !== 0) {
  throw new Error("Failed to list libraries with exit code " + listResult.status);
}

const libraries = JSON.parse(listResult.stdout);
const failures = [];
const client = createWorkerClient();

await client.ping.query();

for (const entry of libraries) {
  const library = entry.name ?? entry.library;

  for (const versionEntry of entry.versions) {
    const version =
      typeof versionEntry === "string"
        ? versionEntry
        : (versionEntry.version ?? versionEntry.ref?.version);
    try {
      await refresh(client, library, version);
    } catch (error) {
      const label = library + "@" + (version || "latest");
      console.error("Failed " + label + ": " + errorMessage(error));
      failures.push(label);
    }
  }
}

if (failures.length > 0) {
  throw new Error(failures.length + " refreshes failed. See errors above.");
}
