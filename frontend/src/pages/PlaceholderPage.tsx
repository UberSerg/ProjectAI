import { Link } from "react-router-dom";
import { PageHeader } from "../components/Ui";

export function PlaceholderPage({
  title,
  description,
  bullets,
}: {
  title: string;
  description: string;
  bullets: string[];
}) {
  return (
    <section>
      <PageHeader title={title} description={description} />
      <article className="panel">
        <p className="muted">Здесь будут:</p>
        <ul className="placeholder-list">
          {bullets.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="muted" style={{ marginTop: "1rem" }}>
          Пока можно продолжить работу с{" "}
          <Link to="/market">рыночными данными</Link> и <Link to="/workflows">процессами</Link>.
        </p>
      </article>
    </section>
  );
}
