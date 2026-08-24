// biome-ignore-all lint/security/noDangerouslySetInnerHtml: This single-purpose component injects build-time SVG from repository-authored Mermaid source.
import { renderMermaidSVG } from "beautiful-mermaid";

export function Mermaid({ chart }: { chart: string }) {
	const svg = renderMermaidSVG(chart, {
		bg: "var(--color-fd-background)",
		fg: "var(--color-fd-foreground)",
		transparent: true,
	});

	return (
		<div
			className="my-6 overflow-x-auto [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-none md:[&_svg]:max-w-full"
			data-mermaid-diagram="true"
			dangerouslySetInnerHTML={{ __html: svg }}
		/>
	);
}
