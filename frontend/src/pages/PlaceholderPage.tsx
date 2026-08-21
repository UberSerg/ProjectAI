type Props = { title: string };

export function PlaceholderPage({ title }: Props) {
  return (
    <section>
      <h1>{title}</h1>
      <p className="subtitle">Section placeholder — content will be added in later stages.</p>
    </section>
  );
}
