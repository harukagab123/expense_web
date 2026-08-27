import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [command, ...args] = process.argv.slice(2);

const black = "#000000";
const white = "#FFFFFF";
const currencyFormat = '"$"#,##0.00;("$"#,##0.00);-';

async function buildWorkbook(inputPath, outputPath) {
  const report = JSON.parse(await fs.readFile(inputPath, "utf8"));
  const workbook = Workbook.create();
  const summary = workbook.worksheets.add("Summary");
  summary.showGridLines = false;

  summary.mergeCells("A1:B1");
  summary.getRange("A1:B1").values = [[`${report.period.label} EXPENSE SUMMARY`]];
  summary.getRange("A1:B1").format = {
    fill: black,
    font: { bold: true, color: white, size: 18 },
    verticalAlignment: "center",
  };
  summary.getRange("A1:B1").format.rowHeight = 34;

  summary.mergeCells("A2:B2");
  summary.getRange("A2:B2").values = [[
    `Reporting period: ${report.period.start_date} through ${report.period.end_date}`,
  ]];
  summary.getRange("A2:B2").format = {
    font: { italic: true, color: black },
    borders: { bottom: { style: "thin", color: black } },
  };

  summary.getRange("A4:B4").values = [["TOTAL INCLUDED EXPENSES", null]];
  summary.getRange("A4:B4").format = {
    font: { bold: true, color: black, size: 13 },
    borders: {
      top: { style: "medium", color: black },
      bottom: { style: "double", color: black },
    },
  };
  summary.getRange("B4").format.numberFormat = currencyFormat;
  summary.getRange("B4").format.horizontalAlignment = "right";

  let row = 7;
  const groupTotalRows = [];
  for (const group of report.groups) {
    summary.mergeCells(`A${row}:B${row}`);
    summary.getRange(`A${row}:B${row}`).values = [[group.label]];
    summary.getRange(`A${row}:B${row}`).format = {
      fill: black,
      font: { bold: true, color: white },
      verticalAlignment: "center",
    };
    summary.getRange(`A${row}:B${row}`).format.rowHeight = 24;
    row += 1;

    summary.getRange(`A${row}:B${row}`).values = [["Subcategory", "Amount"]];
    summary.getRange(`A${row}:B${row}`).format = {
      fill: white,
      font: { bold: true, color: black },
      borders: { bottom: { style: "medium", color: black } },
    };
    summary.getRange(`B${row}`).format.horizontalAlignment = "right";
    row += 1;

    const firstSubcategoryRow = row;
    const rows = group.subcategories.map((subcategory) => [
      subcategory.label,
      Number(subcategory.total),
    ]);
    summary.getRangeByIndexes(row - 1, 0, rows.length, 2).values = rows;
    const lastSubcategoryRow = row + rows.length - 1;
    summary.getRange(`B${row}:B${lastSubcategoryRow}`).format.numberFormat = currencyFormat;
    summary.getRange(`B${row}:B${lastSubcategoryRow}`).format.horizontalAlignment = "right";
    summary.getRange(`A${row}:B${lastSubcategoryRow}`).format.borders = {
      insideHorizontal: { style: "thin", color: black },
    };
    row = lastSubcategoryRow + 1;

    summary.getRange(`A${row}:B${row}`).values = [[`TOTAL ${group.label}`, null]];
    summary.getRange(`B${row}`).formulas = [[`=SUM(B${firstSubcategoryRow}:B${lastSubcategoryRow})`]];
    summary.getRange(`A${row}:B${row}`).format = {
      font: { bold: true, color: black },
      borders: {
        top: { style: "medium", color: black },
        bottom: { style: "double", color: black },
      },
    };
    summary.getRange(`B${row}`).format.numberFormat = currencyFormat;
    summary.getRange(`B${row}`).format.horizontalAlignment = "right";
    groupTotalRows.push(row);
    row += 2;
  }

  summary.getRange(`A${row}:B${row}`).values = [["TOTAL INCLUDED EXPENSES", null]];
  summary.getRange(`B${row}`).formulas = [[
    `=SUM(${groupTotalRows.map((value) => `B${value}`).join(",")})`,
  ]];
  summary.getRange(`A${row}:B${row}`).format = {
    fill: black,
    font: { bold: true, color: white, size: 13 },
    borders: {
      top: { style: "medium", color: black },
      bottom: { style: "double", color: black },
    },
  };
  summary.getRange(`B${row}`).format.numberFormat = currencyFormat;
  summary.getRange(`B${row}`).format.horizontalAlignment = "right";
  summary.getRange("B4").formulas = [[`=B${row}`]];

  summary.getRange("A:A").format.columnWidth = 44;
  summary.getRange("B:B").format.columnWidth = 20;
  summary.freezePanes.freezeRows(2);

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
}

async function inspectWorkbook(inputPath, summaryPreviewPath) {
  const input = await FileBlob.load(inputPath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const summary = workbook.worksheets.getItem("Summary");
  const summaryUsed = summary.getUsedRange();
  const sheetInspection = await workbook.inspect({
    kind: "sheet",
    include: "name",
    maxChars: 2000,
  });
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "summary workbook formula error scan",
  });
  const styles = await workbook.inspect({
    kind: "computedStyle",
    sheetId: "Summary",
    range: `A1:B${(summaryUsed.values || []).length}`,
    maxChars: 5000,
  });
  if (summaryPreviewPath) {
    const preview = await workbook.render({
      sheetName: "Summary",
      autoCrop: "all",
      scale: 1.5,
      format: "png",
    });
    await fs.writeFile(summaryPreviewPath, new Uint8Array(await preview.arrayBuffer()));
  }
  process.stdout.write(JSON.stringify({
    sheets: ["Summary"],
    summaryValues: summaryUsed.values,
    summaryFormulas: summaryUsed.formulas,
    formulaErrors: errors.ndjson,
    computedStyles: styles.ndjson,
    sheetInspection: sheetInspection.ndjson,
  }));
}

if (command === "build" && args.length === 2) {
  await buildWorkbook(args[0], args[1]);
} else if (command === "inspect" && args.length >= 1) {
  await inspectWorkbook(args[0], args[1]);
} else {
  throw new Error("Usage: summary_workbook.mjs build <input.json> <output.xlsx> | inspect <input.xlsx> [summary.png]");
}
