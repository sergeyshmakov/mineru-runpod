// biome-ignore-all lint/security/noDangerouslySetInnerHtml: Serialized JSON-LD built from repository content, not user input.

export function JsonLd({ schema }: { schema: object }) {
	return (
		<script
			type="application/ld+json"
			// `<` cannot appear raw inside a script element.
			dangerouslySetInnerHTML={{
				__html: JSON.stringify(schema).replaceAll("<", "\\u003c"),
			}}
		/>
	);
}
