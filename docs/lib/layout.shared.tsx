import type { BaseLayoutProps } from "fumadocs-ui/layouts/shared";
import { repositoryUrl, runpodReferralUrl, siteName } from "@/lib/site";

export function baseOptions(): BaseLayoutProps {
	return {
		nav: {
			title: (
				<span className="flex items-center gap-2">
					<img src="/favicon.png" alt="" width={24} height={24} />
					<span>{siteName}</span>
				</span>
			),
		},
		githubUrl: repositoryUrl,
		links: [
			{
				text: "Documentation",
				url: "/getting-started/overview/",
				active: "nested-url",
			},
			{
				text: "API reference",
				url: "/reference/api/",
				active: "nested-url",
			},
			{
				text: "Blog",
				url: "/blog/",
				active: "nested-url",
			},
			{
				text: "Deploy on RunPod",
				url: runpodReferralUrl,
				external: true,
			},
		],
	};
}
