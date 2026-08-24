import defaultMdxComponents from "fumadocs-ui/mdx";
import type { ComponentProps } from "react";

const NextImage = defaultMdxComponents.img;

// next/image needs explicit dimensions, and the only way to know them for a
// remote file is to fetch it while building, which would make the build depend
// on someone else's host staying up (see remarkImageOptions in
// source.config.ts). External images therefore render as a plain <img>, the same
// element the Astro site emitted for them. Local images keep the Next component,
// which measures them on disk.
export function MdxImage({ src, alt, ...props }: ComponentProps<"img">) {
	if (typeof src === "string" && /^https?:\/\//.test(src)) {
		return (
			<img
				src={src}
				alt={alt ?? ""}
				loading="lazy"
				decoding="async"
				className="rounded-lg"
				{...props}
			/>
		);
	}

	return (
		<NextImage
			src={src as ComponentProps<typeof NextImage>["src"]}
			alt={alt ?? ""}
			{...props}
		/>
	);
}
