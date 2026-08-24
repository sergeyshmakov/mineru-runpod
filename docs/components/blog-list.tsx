import Link from "next/link";
import type { BlogPost } from "@/lib/blog";
import { formatDate, tagSlug } from "@/lib/blog";

export function BlogList({ posts }: { posts: BlogPost[] }) {
	return (
		<div className="grid gap-5 md:grid-cols-2">
			{posts.map((post) => (
				<article key={post.url} className="rounded-xl border bg-fd-card p-6">
					<p className="text-sm text-fd-muted-foreground">
						{formatDate(post.data.date)}
					</p>
					<h2 className="mt-2 text-xl font-semibold tracking-tight">
						<Link href={`${post.url}/`} className="hover:underline">
							{post.data.title}
						</Link>
					</h2>
					<p className="mt-3 leading-7 text-fd-muted-foreground">
						{post.data.description}
					</p>
					<div className="mt-4 flex flex-wrap gap-2">
						{post.data.tags.map((tag) => (
							<Link
								key={tag}
								href={`/blog/tags/${tagSlug(tag)}/`}
								className="rounded-full border px-2.5 py-1 text-xs text-fd-muted-foreground hover:text-fd-foreground"
							>
								{tag}
							</Link>
						))}
					</div>
				</article>
			))}
		</div>
	);
}
