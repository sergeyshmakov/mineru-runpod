import { runpodReferralUrl } from "@/lib/site";

// The call to action on every page. Fumadocs renders `type: "button"` link items
// as ordinary links inside the docs sidebar, so the CTA is a custom item with
// its own styling to stay a visible button in both the home nav and the sidebar.
export function DeployButton() {
	return (
		<a
			href={runpodReferralUrl}
			rel="noreferrer noopener"
			target="_blank"
			className="inline-flex items-center gap-1.5 rounded-lg bg-fd-primary px-3 py-1.5 text-sm font-medium text-fd-primary-foreground transition-opacity hover:opacity-90"
		>
			Deploy on RunPod
			<svg
				aria-hidden="true"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				strokeWidth="2"
				strokeLinecap="round"
				strokeLinejoin="round"
				className="size-3.5"
			>
				<path d="M7 17 17 7M9 7h8v8" />
			</svg>
		</a>
	);
}
