// estimator.ts の数値は constants.ts か data/ の変数から来る。数値リテラルを持ち込んでいないことを構文木で確かめる。
import { readFileSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const DIR = join(__dirname, "../../../lib/systems/man-hours");

function parse(file: string): ts.SourceFile {
  return ts.createSourceFile(file, readFileSync(join(DIR, file), "utf-8"), ts.ScriptTarget.ES2022, true);
}

function collect(source: ts.SourceFile, predicate: (node: ts.Node) => string | null): string[] {
  const found: string[] = [];
  const visit = (node: ts.Node) => {
    const text = predicate(node);
    if (text !== null) {
      const { line } = source.getLineAndCharacterOfPosition(node.getStart());
      found.push(`${line + 1}: ${text}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

describe("数値リテラルを持たない", () => {
  const estimator = parse("estimator.ts");

  it("estimator.ts に数値リテラルがない", () => {
    const literals = collect(estimator, (node) =>
      ts.isNumericLiteral(node) || ts.isBigIntLiteral(node) ? node.getText() : null,
    );
    expect(literals, `数値リテラルが残っている: ${literals.join(", ")}`).toEqual([]);
  });

  it("数値を表す文字列を隠し持っていない", () => {
    const numeric = /^\s*-?\d+(\.\d+)?\s*$|^0?\d+[dfe%]$/;
    const hidden = collect(estimator, (node) =>
      (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && numeric.test(node.text)
        ? node.getText()
        : null,
    );
    expect(hidden, `数値を表す文字列が残っている: ${hidden.join(", ")}`).toEqual([]);
  });

  it("constants.ts の定数名はすべて大文字", () => {
    const constants = parse("constants.ts");
    const names: string[] = [];
    constants.forEachChild((node) => {
      if (ts.isVariableStatement(node)) {
        for (const declaration of node.declarationList.declarations) {
          names.push(declaration.name.getText());
        }
      }
    });
    expect(names.length).toBeGreaterThan(0);
    expect(names.filter((name) => name !== name.toUpperCase())).toEqual([]);
  });
});
