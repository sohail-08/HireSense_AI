export function PlaceholderPage({
  title,
}: {
  title: string;
}) {
  return (
    <section className="panel">
      <h1>{title}</h1>

      <p>
        This page is connected to navigation.
        Its functionality will be implemented
        in a later milestone.
      </p>
    </section>
  );
}