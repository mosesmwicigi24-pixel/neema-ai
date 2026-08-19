import { Button } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-32 text-center">
      <p className="font-display text-5xl text-brand-600">404</p>
      <h1 className="mt-4 text-2xl font-extrabold tracking-tight text-ink-900">
        We couldn&rsquo;t find that page
      </h1>
      <p className="mt-4 leading-relaxed text-ink-700">
        The page you are looking for may have moved or no longer exists.
      </p>
      <div className="mt-8">
        <Button href="/">Back to the home page</Button>
      </div>
    </div>
  );
}
