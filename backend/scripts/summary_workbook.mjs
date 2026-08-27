import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [command, ...args] = process.argv.slice(2);

const currencyFormat = '"$"#,##0.00;[Red]("$"#,##0.00);-';
const darkBlue = "#16324F";
const mediumBlue = "#2D5F82";
const lightBlue = "#EAF2F8";
const paleGreen = "#E8F5E9";
const paleAmber = "#FFF4D6";
const borderColor = "#CBD5E1";

async function buildWorkbook(inputPath, outputPath) {
  const report = JSON.parse(await fs.readFile(inputPath, "utf8"));
  const workbook = Workbook.create();
  const summary = workbook.worksheets.add("Summary");
  const detail = workbook.worksheets.add("Transaction Detail");
  summary.showGridLines = false;
  detail.showGridLines = false;

  const detailRows = [];
  for (const group of report.groups) {
    for (const subcategory of group.subcategories) {
      for (const transaction of subcategory.transactions) {
        detailRows.push([
          new Date(`${transaction.transaction_date}T00:00:00`),
          transaction.normalized_name || transaction.transaction_detail,
          transaction.transaction_detail,
          transaction.institution,
          transaction.source_file,
          transaction.transaction_type,
          group.label,
          subcategory.label,
          Number(transaction.amount),
          transaction.review_status,
          transaction.category_status,
          transaction.source_file_available ? "Available" : "Source file no longer retained",
        ]);
      }
    }
  }

  const detailHeaders = [[
    "Date",
    "Name",
    "Transaction Detail",
    "Institution",
    "Source File",
    "Transaction Type",
    "Main Category",
    "Subcategory",
    "Amount",
    "Review Status",
    "Category Status",
    "Source Status",
  ]];
  detail.getRange("A1:L1").values = detailHeaders;
  if (detailRows.length > 0) {
    detail.getRangeByIndexes(1, 0, detailRows.length, detailHeaders[0].length).values = detailRows;
    detail.tables.add(`A1:L${detailRows.length + 1}`, true, "ExpenseTransactionDetail");
  }
  detail.getRange("A1:L1").format = {
    fill: darkBlue,
    font: { bold: true, color: "#FFFFFF" },
    verticalAlignment: "center",
    wrapText: true,
  };
  detail.getRange("A:A").format.columnWidth = 12;
  detail.getRange("B:B").format.columnWidth = 24;
  detail.getRange("C:C").format.columnWidth = 38;
  detail.getRange("D:D").format.columnWidth = 16;
  detail.getRange("E:E").format.columnWidth = 28;
  detail.getRange("F:F").format.columnWidth = 20;
  detail.getRange("G:G").format.columnWidth = 34;
  detail.getRange("H:H").format.columnWidth = 32;
  detail.getRange("I:I").format.columnWidth = 15;
  detail.getRange("J:J").format.columnWidth = 18;
  detail.getRange("K:K").format.columnWidth = 18;
  detail.getRange("L:L").format.columnWidth = 30;
  if (detailRows.length > 0) {
    detail.getRange(`A2:A${detailRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
    detail.getRange(`I2:I${detailRows.length + 1}`).format.numberFormat = currencyFormat;
    detail.getRange(`A2:L${detailRows.length + 1}`).format.borders = {
      insideHorizontal: { style: "thin", color: borderColor },
    };
  }
  detail.freezePanes.freezeRows(1);

  summary.mergeCells("A1:C1");
  summary.getRange("A1:C1").values = [[`${report.period.label} EXPENSE SUMMARY`]];
  summary.getRange("A1:C1").format = {
    fill: darkBlue,
    font: { bold: true, color: "#FFFFFF", size: 18 },
    verticalAlignment: "center",
  };
  summary.getRange("A1:C1").format.rowHeight = 32;
  summary.mergeCells("A2:C2");
  summary.getRange("A2:C2").values = [[
    `Reporting period: ${report.period.start_date} through ${report.period.end_date}`,
  ]];
  summary.getRange("A2:C2").format = { font: { italic: true, color: "#475569" } };

  summary.getRange("A4:B4").values = [["Overview", "Value"]];
  summary.getRange("A4:B4").format = {
    fill: mediumBlue,
    font: { bold: true, color: "#FFFFFF" },
  };
  summary.getRange("A5:B8").values = [
    ["Total Included Expenses", Number(report.grand_total)],
    ["Selected Transactions", report.metrics.contributing_transaction_count],
    ["Needs Review", report.metrics.needs_review_count],
    ["Statements / Sources", report.metrics.source_count],
  ];
  summary.getRange("B5").format.numberFormat = currencyFormat;
  summary.getRange("A5:B8").format.borders = {
    insideHorizontal: { style: "thin", color: borderColor },
    outside: { style: "thin", color: borderColor },
  };
  summary.getRange("A5:B5").format = { fill: paleGreen, font: { bold: true } };
  if (report.metrics.needs_review_count > 0) {
    summary.getRange("A7:B7").format = { fill: paleAmber, font: { bold: true } };
  }

  const detailEndRow = Math.max(detailRows.length + 1, 2);
  let row = 10;
  const groupTotalRows = [];
  for (const group of report.groups) {
    const groupHeaderRow = row;
    summary.mergeCells(`A${row}:C${row}`);
    summary.getRange(`A${row}:C${row}`).values = [[group.label]];
    summary.getRange(`A${row}:C${row}`).format = {
      fill: darkBlue,
      font: { bold: true, color: "#FFFFFF" },
      verticalAlignment: "center",
    };
    row += 1;
    summary.getRange(`A${row}:C${row}`).values = [["Subcategory", "Transactions", "Amount"]];
    summary.getRange(`A${row}:C${row}`).format = {
      fill: lightBlue,
      font: { bold: true, color: darkBlue },
      borders: { bottom: { style: "thin", color: borderColor } },
    };
    summary.getRange(`B${row}`).format.horizontalAlignment = "center";
    summary.getRange(`C${row}`).format.horizontalAlignment = "right";
    row += 1;
    const firstSubcategoryRow = row;
    for (const subcategory of group.subcategories) {
      summary.getRange(`A${row}`).values = [[subcategory.label]];
      summary.getRange(`B${row}`).formulas = [[
        `=COUNTIFS('Transaction Detail'!$G$2:$G$${detailEndRow},$A$${groupHeaderRow},'Transaction Detail'!$H$2:$H$${detailEndRow},$A${row})`,
      ]];
      summary.getRange(`C${row}`).formulas = [[
        `=SUMIFS('Transaction Detail'!$I$2:$I$${detailEndRow},'Transaction Detail'!$G$2:$G$${detailEndRow},$A$${groupHeaderRow},'Transaction Detail'!$H$2:$H$${detailEndRow},$A${row})`,
      ]];
      summary.getRange(`B${row}:C${row}`).format.font = { color: "#008000" };
      row += 1;
    }
    const lastSubcategoryRow = row - 1;
    summary.getRange(`A${row}:C${row}`).values = [[`TOTAL ${group.label}`, null, null]];
    summary.getRange(`B${row}`).formulas = [[`=SUM(B${firstSubcategoryRow}:B${lastSubcategoryRow})`]];
    summary.getRange(`C${row}`).formulas = [[`=SUM(C${firstSubcategoryRow}:C${lastSubcategoryRow})`]];
    summary.getRange(`A${row}:C${row}`).format = {
      font: { bold: true },
      borders: { top: { style: "medium", color: darkBlue }, bottom: { style: "double", color: darkBlue } },
    };
    groupTotalRows.push(row);
    row += 2;
  }

  summary.getRange(`A${row}:C${row}`).values = [["TOTAL INCLUDED EXPENSES", null, null]];
  summary.getRange(`B${row}`).formulas = [[`=SUM(${groupTotalRows.map((value) => `B${value}`).join(",")})`]];
  summary.getRange(`C${row}`).formulas = [[`=SUM(${groupTotalRows.map((value) => `C${value}`).join(",")})`]];
  summary.getRange(`A${row}:C${row}`).format = {
    fill: darkBlue,
    font: { bold: true, color: "#FFFFFF" },
    borders: { top: { style: "medium", color: darkBlue }, bottom: { style: "double", color: darkBlue } },
  };
  const grandTotalRow = row;
  summary.getRange("B5").formulas = [[`=C${grandTotalRow}`]];
  row += 2;
  summary.getRange(`A${row}:C${row}`).values = [["Reconciliation Check", null, null]];
  summary.getRange(`A${row}:C${row}`).format = { fill: lightBlue, font: { bold: true, color: darkBlue } };
  row += 1;
  summary.getRange(`A${row}:C${row}`).values = [["Transaction Detail Sum", null, null]];
  summary.getRange(`C${row}`).formulas = [[`=SUM('Transaction Detail'!$I$2:$I$${detailEndRow})`]];
  summary.getRange(`C${row}`).format.font = { color: "#008000" };
  row += 1;
  summary.getRange(`A${row}:C${row}`).values = [["Difference", null, null]];
  summary.getRange(`C${row}`).formulas = [[`=C${grandTotalRow}-C${row - 1}`]];
  summary.getRange(`A${row}:C${row}`).format = { fill: paleGreen, font: { bold: true } };

  summary.getRange(`B5:B${row}`).format.horizontalAlignment = "right";
  summary.getRange(`C10:C${row}`).format.numberFormat = currencyFormat;
  summary.getRange(`B10:B${row}`).format.numberFormat = "#,##0";
  summary.getRange(`A10:C${row}`).format.borders = {
    insideHorizontal: { style: "thin", color: "#E2E8F0" },
  };
  summary.getRange("A:A").format.columnWidth = 42;
  summary.getRange("B:B").format.columnWidth = 20;
  summary.getRange("C:C").format.columnWidth = 20;
  summary.freezePanes.freezeRows(2);

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
}

async function inspectWorkbook(inputPath, summaryPreviewPath, detailPreviewPath) {
  const input = await FileBlob.load(inputPath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const summary = workbook.worksheets.getItem("Summary");
  const detail = workbook.worksheets.getItem("Transaction Detail");
  const summaryUsed = summary.getUsedRange();
  const detailUsed = detail.getUsedRange();
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "summary workbook formula error scan",
  });
  if (summaryPreviewPath) {
    const preview = await workbook.render({ sheetName: "Summary", autoCrop: "all", scale: 1.5, format: "png" });
    await fs.writeFile(summaryPreviewPath, new Uint8Array(await preview.arrayBuffer()));
  }
  if (detailPreviewPath) {
    const preview = await workbook.render({
      sheetName: "Transaction Detail",
      range: `A1:L${Math.min((detailUsed.values || []).length, 30)}`,
      scale: 1.2,
      format: "png",
    });
    await fs.writeFile(detailPreviewPath, new Uint8Array(await preview.arrayBuffer()));
  }
  process.stdout.write(JSON.stringify({
    sheets: ["Summary", "Transaction Detail"],
    summaryValues: summaryUsed.values,
    summaryFormulas: summaryUsed.formulas,
    detailValues: detailUsed.values,
    formulaErrors: errors.ndjson,
  }));
}

if (command === "build" && args.length === 2) {
  await buildWorkbook(args[0], args[1]);
} else if (command === "inspect" && args.length >= 1) {
  await inspectWorkbook(args[0], args[1], args[2]);
} else {
  throw new Error("Usage: summary_workbook.mjs build <input.json> <output.xlsx> | inspect <input.xlsx> [summary.png] [detail.png]");
}
