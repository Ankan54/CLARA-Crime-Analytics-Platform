import type { TableArtifact } from "../../lib/assistantTypes";

export function TableArtifactView({ artifact }: { artifact: TableArtifact }) {
  return (
    <div className="table-artifact">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {artifact.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {artifact.rows.length === 0 ? (
              <tr>
                <td colSpan={artifact.columns.length} className="muted">
                  No rows returned.
                </td>
              </tr>
            ) : (
              artifact.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell ?? "—"}</td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {artifact.caption && <p className="artifact-caption">{artifact.caption}</p>}
    </div>
  );
}
