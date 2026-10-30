import { highlight } from "fumadocs-core/highlight";
import { Card, Cards } from "fumadocs-ui/components/card";
import { CodeBlock } from "fumadocs-ui/components/codeblock";
import type { Metadata } from "next";
import Link from "next/link";
import { pageMetadata } from "@/lib/metadata";
import { modelCardUrl, repositoryUrl, runpodReferralUrl } from "@/lib/site";

const quickStartCode = `from mineru_client import MineruClient

client = MineruClient(endpoint_id="<your-endpoint-id>")
result = client.parse_document(file_url="https://example.com/report.pdf", page_range="1-5")
client.save_tarball(result, "./out/doc")
# → doc.md + content lists + middle.json + structured content + images/`;

const homeDescription =
	"Deploy MinerU 4.1 on RunPod Serverless in two clicks. The open-source endpoint scales to zero and returns Markdown, structured JSON, and images.";

export const metadata: Metadata = pageMetadata({
	title: "Deploy MinerU on RunPod Serverless",
	description: homeDescription,
	path: "/",
});

export default async function HomePage() {
	const quickStart = await highlight(quickStartCode, { lang: "python" });

	return (
		<main className="relative flex flex-1 flex-col overflow-hidden">
			<div
				aria-hidden
				className="rm-hero-grid pointer-events-none absolute inset-0 opacity-70"
			/>
			<section className="relative mx-auto w-full max-w-6xl px-6 py-20 sm:py-28">
				<div className="grid items-center gap-12 lg:grid-cols-[minmax(0,12fr)_minmax(0,9fr)]">
					<div>
						<h1 className="text-balance text-4xl font-semibold tracking-tight sm:text-6xl">
							Deploy MinerU 4.1 on RunPod in two clicks
						</h1>
						<p className="mt-6 max-w-2xl text-pretty text-lg leading-8 text-fd-muted-foreground sm:text-xl">
							Open-source RunPod Serverless template. Your endpoint scales to
							zero and bills by the second, so an idle endpoint costs nothing.
							{/* MEASURE: best-case warm $/page on the 2.x default tier
							    (standard) on a 24 GB RTX 4090, before a per-page price
							    returns to this line */}
						</p>
						<div className="mt-9 flex flex-wrap gap-3">
							<a
								href={runpodReferralUrl}
								rel="noreferrer noopener"
								target="_blank"
								className="rounded-lg bg-fd-primary px-5 py-3 font-medium text-fd-primary-foreground transition-opacity hover:opacity-90"
							>
								Deploy on RunPod
							</a>
							<Link
								href="/getting-started/overview/"
								className="rounded-lg border bg-fd-background px-5 py-3 font-medium transition-colors hover:bg-fd-accent"
							>
								Get started
							</Link>
							<a
								href={repositoryUrl}
								rel="noreferrer noopener"
								target="_blank"
								className="rounded-lg border bg-fd-background px-5 py-3 font-medium transition-colors hover:bg-fd-accent"
							>
								GitHub
							</a>
							<a
								href={modelCardUrl}
								rel="noreferrer noopener"
								target="_blank"
								className="rounded-lg border bg-fd-background px-5 py-3 font-medium transition-colors hover:bg-fd-accent"
							>
								MinerU model card
							</a>
						</div>
					</div>
					{/* Abstract rather than figurative: this project's own mark — a
					    document with a folded corner — at hero scale, a stack of them
					    resolving into content. One hue at varying opacity, so it needs
					    no second version for dark mode. */}
					<img
						src="/hero.svg"
						alt="Abstract stack of documents resolved into structured content"
						width={440}
						height={440}
						loading="eager"
						decoding="async"
						className="mx-auto hidden h-auto w-full max-w-md lg:block"
					/>
				</div>

				<section className="mt-20">
					<h2 className="text-3xl font-semibold tracking-tight">
						How it works
					</h2>
					<div className="mt-5 max-w-4xl space-y-4 leading-7 text-fd-muted-foreground">
						<p>
							This is an open-source repo and{" "}
							<a
								href={runpodReferralUrl}
								rel="noreferrer noopener"
								target="_blank"
								className="text-fd-foreground underline underline-offset-4"
							>
								RunPod Hub
							</a>{" "}
							template — not a hosted service. Deploy it from the Hub (or fork
							it for full control), and the worker runs on{" "}
							<strong className="text-fd-foreground">your</strong> RunPod
							account against{" "}
							<strong className="text-fd-foreground">your</strong> wallet.
						</p>
						<p>
							Under the hood it is one Docker image running the official{" "}
							<a
								href="https://github.com/opendatalab/MinerU"
								rel="noreferrer noopener"
								target="_blank"
								className="text-fd-foreground underline underline-offset-4"
							>
								MinerU
							</a>{" "}
							4.1.x release, with its small models and the{" "}
							<code>MinerU2.5-Pro-2605-1.2B</code> VLM baked in. Send a PDF,
							image, Office file, EPUB or HTML page as a URL, base64 blob, or
							path on a mounted volume, and pick one of MinerU&apos;s four
							tiers, from <code>flash</code> to <code>advanced</code>, where
							the VLM reads the layout itself. Get back Markdown, a structured{" "}
							<code>content_list</code>, MinerU&apos;s <code>middle.json</code>,
							extracted images, and on request HTML, LaTeX, DOCX, EPUB or PDF
							renders. When traffic stops, RunPod tears the worker down in
							seconds.
						</p>
					</div>
				</section>

				<section className="mt-16">
					<h2 className="text-3xl font-semibold tracking-tight">
						What you get
					</h2>
					<Cards className="mt-6">
						<Card
							title="MinerU 4.1 output"
							description={
								<>
									Four quality tiers, from a fast text-layer pass to the
									MinerU2.5-Pro 1.2B VLM, produce Markdown, tables, formulas,
									reading order, and structured JSON. See the{" "}
									<a
										href={modelCardUrl}
										rel="noreferrer noopener"
										target="_blank"
										className="underline underline-offset-4"
									>
										model card
									</a>{" "}
									for benchmark scope and limitations.
								</>
							}
						/>
						<Card
							title="Pay per second, not per hour"
							description={
								<>
									RunPod bills a worker by the second and scales it to zero
									between bursts. The tier, content density and cold starts set
									the real cost; see{" "}
									<Link
										href="/guides/choosing-gpu/"
										className="underline underline-offset-4"
									>
										Choosing a GPU
									</Link>
									.
									{/* MEASURE: warm $/page per tier on a 24 GB RTX 4090 under
									    2.x; the 1.x figure was measured on MinerU 3.4 and does
									    not carry over */}
								</>
							}
						/>
						<Card
							title="No glue code"
							description="Deploy from the Hub in one click, or fork and let RunPod auto-build your copy. Either way: ten minutes from sign-up to first parse."
						/>
						<Card
							title="Published license terms"
							description={
								<>
									MinerU uses an{" "}
									<a
										href="https://github.com/opendatalab/MinerU/blob/master/LICENSE.md"
										rel="noreferrer noopener"
										target="_blank"
										className="underline underline-offset-4"
									>
										open-source license
									</a>{" "}
									based on Apache 2.0 with additional terms and stated
									commercial thresholds. Review those terms for your use case.
								</>
							}
						/>
					</Cards>
				</section>

				<section className="mt-16">
					<h2 className="text-3xl font-semibold tracking-tight">
						Try it in 30 seconds
					</h2>
					<CodeBlock className="mt-6 max-w-4xl">{quickStart}</CodeBlock>
				</section>

				<section className="mt-16">
					<h2 className="text-3xl font-semibold tracking-tight">
						Pick your starting point
					</h2>
					<Cards className="mt-6">
						<Card
							title="How it's built"
							href="/getting-started/overview/"
							description="Architecture, what's in the repo, supported workloads, and how it compares to Marker, GROBID, and Nougat."
						/>
						<Card
							title="Deploy in 10 minutes"
							href="/getting-started/deploy/"
							description="Sign up for RunPod, deploy mineru-runpod from the Hub, paste the endpoint id, parse your first PDF."
						/>
						<Card
							title="Pick the right GPU"
							href="/guides/choosing-gpu/"
							description="Which RunPod GPU pool fits your tier and workload shape, what MinerU 4 does with the VRAM it is given, and when a bigger card pays off."
						/>
						<Card
							title="When something breaks"
							href="/guides/troubleshooting/"
							description="Hub build flakes, CUDA driver mismatches, OOM, cold starts. How to read the debug block to diagnose anything else."
						/>
						<Card
							title="Observe production jobs"
							href="/guides/observability/"
							description="Export structured logs, traces, and GPU metrics to any OTLP/HTTP backend with the OpenTelemetry exporter already included in the image."
						/>
						<Card
							title="The source"
							href={repositoryUrl}
							external
							description="The wrapper code is MIT-licensed; MinerU and its model retain their own terms. Issues and PRs are welcome."
						/>
						<Card
							title="Blog"
							href="/blog/"
							description="Project notes and announcements."
						/>
					</Cards>
				</section>
			</section>
		</main>
	);
}
