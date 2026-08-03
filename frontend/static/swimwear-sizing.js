(function () {
  "use strict";

  const cm = (low, high = low) => [low, high];
  const fromInches = (low, high) => [Number((low * 2.54).toFixed(1)), Number((high * 2.54).toFixed(1))];

  const BRAND_ORDER = ["speedo", "arena", "tyr", "mizuno", "nike"];
  const BRAND_ALIASES = {
    speedo: ["speedo", "스피도"],
    arena: ["arena", "아레나"],
    tyr: ["tyr", "티어"],
    mizuno: ["mizuno", "미즈노"],
    nike: ["nike", "나이키"],
  };
  const RACE_MODEL_PATTERN = /fastskin|lzr|powerskin|carbon|primo|st\s*next|gx[\s-]*sonic|avictor|venzo|tech\s*suit|테크\s*수트|레이싱/i;

  const CHARTS = {
    women: {
      speedo: {
        name: "Speedo",
        scope: "여성 일반·훈련용 미국 공식몰 표",
        regionCode: "us",
        regionLabel: "미국 공식몰(en-US)",
        labelSystem: "Speedo 숫자 라벨",
        note: "Speedo 숫자 표기 기준입니다. Fastskin은 모델 전용 표를 사용하세요.",
        source: "https://speedo.com/en-us/pages/size-guides",
        rows: [
          { size: "28", bust: cm(74, 78), waist: cm(56, 60), hip: cm(81, 85) },
          { size: "30", bust: cm(79, 83), waist: cm(61, 65), hip: cm(86, 90) },
          { size: "32", bust: cm(84, 87), waist: cm(66, 69), hip: cm(91, 94) },
          { size: "34", bust: cm(88, 92), waist: cm(70, 74), hip: cm(95, 99) },
          { size: "36", bust: cm(93, 98), waist: cm(75, 80), hip: cm(100, 105) },
          { size: "38", bust: cm(99, 103), waist: cm(81, 85), hip: cm(106, 110) },
          { size: "40", bust: cm(104, 108), waist: cm(86, 90), hip: cm(111, 115) },
          { size: "42", bust: cm(109, 113), waist: cm(91, 95), hip: cm(116, 120) },
          { size: "44", bust: cm(114, 118), waist: cm(96, 100), hip: cm(121, 125) },
          { size: "46", bust: cm(119, 123), waist: cm(101, 105), hip: cm(126, 131) },
        ],
      },
      arena: {
        name: "arena",
        scope: "여성 일반 수영복 국제몰 표",
        regionCode: "intl",
        regionLabel: "arena 국제몰(en_ROW)",
        labelSystem: "국제몰 숫자 라벨",
        note: "공식표의 기준 신체 치수입니다. 국내 유통 제품은 라벨 체계를 다시 확인하세요.",
        source: "https://www.arenasport.com/en_row/size-guide/women",
        pointValues: true,
        rows: [
          { size: "32", bust: cm(75), waist: cm(58), hip: cm(87) },
          { size: "34", bust: cm(80), waist: cm(63), hip: cm(88) },
          { size: "36", bust: cm(85), waist: cm(65), hip: cm(90) },
          { size: "38", bust: cm(90), waist: cm(70), hip: cm(95) },
          { size: "40", bust: cm(95), waist: cm(75), hip: cm(100) },
          { size: "42", bust: cm(100), waist: cm(80), hip: cm(105) },
          { size: "44", bust: cm(105), waist: cm(85), hip: cm(110) },
          { size: "46", bust: cm(110), waist: cm(90), hip: cm(115) },
          { size: "48", bust: cm(115), waist: cm(95), hip: cm(120) },
          { size: "50", bust: cm(120), waist: cm(100), hip: cm(125) },
          { size: "52", bust: cm(125), waist: cm(105), hip: cm(130) },
          { size: "54", bust: cm(130), waist: cm(110), hip: cm(135) },
        ],
      },
      tyr: {
        name: "TYR",
        scope: "여성 Performance 성인 표",
        regionCode: "us",
        regionLabel: "미국 공식몰(TYR US)",
        labelSystem: "미국 Performance 숫자 라벨",
        note: "미국 공식 Performance 숫자 표기입니다. 테크수트는 전용 표를 확인하세요.",
        source: "https://tyr.com/pages/sizing-swim",
        rows: [
          { size: "24", aliases: ["XXS"], bust: fromInches(28, 29), waist: fromInches(23, 24), hip: fromInches(30, 31), torso: fromInches(55, 56.5) },
          { size: "26", aliases: ["XS"], bust: fromInches(30, 31), waist: fromInches(25, 26), hip: fromInches(32, 33), torso: fromInches(57, 58.5) },
          { size: "28", aliases: ["S"], bust: fromInches(32, 33), waist: fromInches(27, 28), hip: fromInches(34, 35), torso: fromInches(59, 60) },
          { size: "30", bust: fromInches(34, 35), waist: fromInches(29, 30), hip: fromInches(35, 37), torso: fromInches(60, 61) },
          { size: "32", aliases: ["M"], bust: fromInches(35, 36.5), waist: fromInches(31, 32), hip: fromInches(37.5, 38.5), torso: fromInches(61.5, 62.5) },
          { size: "34", bust: fromInches(36.5, 37), waist: fromInches(32.5, 33.5), hip: fromInches(39, 40.5), torso: fromInches(63, 64) },
          { size: "36", aliases: ["L"], bust: fromInches(37, 38.5), waist: fromInches(34, 35.5), hip: fromInches(41, 42), torso: fromInches(65, 66.5) },
          { size: "38", aliases: ["XL"], bust: fromInches(39, 40.5), waist: fromInches(35.5, 36.5), hip: fromInches(42.5, 43.5), torso: fromInches(66, 67) },
          { size: "40", aliases: ["1X"], bust: fromInches(41, 42.5), waist: fromInches(37, 38), hip: fromInches(44, 45), torso: fromInches(67.5, 68.5) },
          { size: "42", aliases: ["2X"], bust: fromInches(43, 44), waist: fromInches(39, 40), hip: fromInches(45.5, 46.5), torso: fromInches(68.5, 69.5) },
        ],
      },
      mizuno: {
        name: "Mizuno",
        scope: "여성 일반 수영복 JIS 표",
        regionCode: "jp",
        regionLabel: "일본 공식몰(JIS)",
        labelSystem: "일본 JIS 문자 라벨",
        note: "일본 공식 일반 수영복 표입니다. GX-SONIC은 모델 전용 표를 사용하세요.",
        source: "https://jpn.mizuno.com/ec/include_html/size/size_swim.html",
        rows: [
          { size: "XS", aliases: ["SS"], bust: cm(75, 79), hip: cm(83, 87) },
          { size: "S", bust: cm(78, 82), hip: cm(86, 90) },
          { size: "M", bust: cm(81, 85), hip: cm(89, 93) },
          { size: "L", bust: cm(84, 88), hip: cm(92, 96) },
          { size: "XL", aliases: ["O"], bust: cm(87, 91), hip: cm(95, 99) },
          { size: "2XL", aliases: ["XO"], bust: cm(90, 94), hip: cm(98, 102) },
        ],
      },
      nike: {
        name: "Nike Swim",
        scope: "여성 수영복 한국 표",
        regionCode: "kr",
        regionLabel: "나이키 코리아(KR)",
        labelSystem: "문자·KR 숫자 병기",
        note: "KR 라벨을 함께 표시합니다. 두 치수가 갈리면 Nike는 엉덩이 치수를 우선 안내합니다.",
        source: "https://www.nike.com/kr/size-fit/womens-swimsuit",
        rows: [
          { size: "XS (KR 80)", aliases: ["XS", "80"], bust: fromInches(31.5, 33.5), waist: fromInches(24, 26), hip: fromInches(34.5, 36.5), torso: fromInches(55, 57.75) },
          { size: "S (KR 85)", aliases: ["S", "85"], bust: fromInches(33.5, 35.5), waist: fromInches(26, 28), hip: fromInches(36.5, 38.5), torso: fromInches(57.75, 60.5) },
          { size: "M (KR 90)", aliases: ["M", "90"], bust: fromInches(35.5, 37.5), waist: fromInches(28, 30), hip: fromInches(38.5, 40.5), torso: fromInches(60.5, 63.25) },
          { size: "L (KR 95)", aliases: ["L", "95"], bust: fromInches(37.5, 40.5), waist: fromInches(30, 33), hip: fromInches(40.5, 43.5), torso: fromInches(63.25, 66) },
          { size: "XL (KR 100)", aliases: ["XL", "100"], bust: fromInches(40.5, 43.5), waist: fromInches(33, 36), hip: fromInches(43.5, 46.5), torso: fromInches(66, 68.5) },
          { size: "2XL (KR 105)", aliases: ["2XL", "XXL", "105"], bust: fromInches(43.5, 46.5), waist: fromInches(36, 39), hip: fromInches(46.5, 49.5), torso: fromInches(68.5, 70.25) },
        ],
      },
    },
    men: {
      speedo: {
        name: "Speedo",
        scope: "남성 일반·훈련용 미국 공식몰 표",
        regionCode: "us",
        regionLabel: "미국 공식몰(en-US)",
        labelSystem: "Speedo 숫자 라벨",
        note: "일반/훈련용 재머 기준입니다. Fastskin은 압박과 표가 달라 전용 표가 필요합니다.",
        source: "https://speedo.com/en-us/pages/size-guides",
        rows: [
          { size: "26", waist: cm(70, 72.5), hip: cm(80, 82.5) },
          { size: "28", waist: cm(73.5, 76), hip: cm(84, 86.5) },
          { size: "30", waist: cm(77.5, 80), hip: cm(87.5, 90) },
          { size: "32", waist: cm(81.5, 85), hip: cm(91.5, 95.5) },
          { size: "34", waist: cm(86.5, 90), hip: cm(96.5, 100.5) },
          { size: "36", waist: cm(91.5, 95.5), hip: cm(101.5, 105.5) },
          { size: "38", waist: cm(96.5, 101.5), hip: cm(106.5, 111.5) },
          { size: "40", waist: cm(102, 107), hip: cm(112, 117) },
          { size: "42", waist: cm(107.5, 112.5), hip: cm(117.5, 122.5) },
          { size: "44", waist: cm(115.5, 119), hip: cm(126, 132) },
        ],
      },
      arena: {
        name: "arena",
        scope: "남성 일반 수영복 국제몰 표",
        regionCode: "intl",
        regionLabel: "arena 국제몰(en_ROW)",
        labelSystem: "국제몰 숫자 라벨",
        note: "공식표의 기준 신체 치수입니다. 국내 제품의 숫자 라벨과 동일한 체계인지 확인하세요.",
        source: "https://www.arenasport.com/en_row/size-guide/men",
        pointValues: true,
        rows: [
          { size: "65", chest: cm(84), waist: cm(69), hip: cm(84) },
          { size: "70", chest: cm(88), waist: cm(73), hip: cm(88) },
          { size: "75", chest: cm(90), waist: cm(75), hip: cm(90) },
          { size: "80", chest: cm(95), waist: cm(80), hip: cm(95) },
          { size: "85", chest: cm(100), waist: cm(85), hip: cm(100) },
          { size: "90", chest: cm(105), waist: cm(90), hip: cm(105) },
          { size: "95", chest: cm(110), waist: cm(95), hip: cm(110) },
          { size: "100", chest: cm(115), waist: cm(100), hip: cm(115) },
          { size: "105", chest: cm(120), waist: cm(105), hip: cm(120) },
          { size: "110", chest: cm(125), waist: cm(110), hip: cm(125) },
        ],
      },
      tyr: {
        name: "TYR",
        scope: "남성 Performance 성인 표",
        regionCode: "us",
        regionLabel: "미국 공식몰(TYR US)",
        labelSystem: "미국 Performance 숫자 라벨",
        note: "미국 공식 Performance 숫자 표기입니다. Avictor 등 테크수트는 전용 표를 확인하세요.",
        source: "https://tyr.com/pages/sizing-swim",
        rows: [
          { size: "26", aliases: ["XS"], waist: fromInches(26, 27.5), hip: fromInches(32, 33) },
          { size: "28", aliases: ["S"], waist: fromInches(28, 29.5), hip: fromInches(35, 37) },
          { size: "30", waist: fromInches(30, 31.5), hip: fromInches(37, 39) },
          { size: "32", aliases: ["M"], waist: fromInches(32, 34), hip: fromInches(39.5, 40.5) },
          { size: "34", waist: fromInches(34.5, 36), hip: fromInches(40.5, 42) },
          { size: "36", aliases: ["L"], waist: fromInches(36.5, 38.5), hip: fromInches(42, 44) },
          { size: "38", aliases: ["XL"], waist: fromInches(39, 41), hip: fromInches(44, 46) },
          { size: "40", aliases: ["2XL"], waist: fromInches(41.5, 44), hip: fromInches(46, 48) },
        ],
      },
      mizuno: {
        name: "Mizuno",
        scope: "남성 일반 수영복 JIS 표",
        regionCode: "jp",
        regionLabel: "일본 공식몰(JIS)",
        labelSystem: "일본 JIS 문자 라벨",
        note: "일본 공식 일반 수영복 표입니다. GX-SONIC은 모델별 전용 표를 사용하세요.",
        source: "https://jpn.mizuno.com/ec/include_html/size/size_swim.html",
        rows: [
          { size: "XS", aliases: ["SS"], waist: cm(67, 73) },
          { size: "S", waist: cm(71, 77) },
          { size: "M", waist: cm(75, 81) },
          { size: "L", waist: cm(79, 85) },
          { size: "XL", aliases: ["O"], waist: cm(83, 89) },
          { size: "2XL", aliases: ["XO"], waist: cm(87, 93) },
        ],
      },
      nike: {
        name: "Nike Swim",
        scope: "남성 트레이닝 수영복 한국 공식몰 표",
        regionCode: "kr",
        regionLabel: "나이키 코리아(KR)",
        labelSystem: "한국 공식몰 숫자 라벨",
        note: "압박감 있는 트레이닝 라인 숫자 표기입니다. 편한 핏을 원하면 제조사는 한 치수 크게 안내합니다.",
        source: "https://www.nike.com/kr/size-fit/mens-training-swimsuit",
        rows: [
          { size: "26", aliases: ["S"], waist: fromInches(27, 29), hip: fromInches(33, 35) },
          { size: "28", waist: fromInches(29, 31), hip: fromInches(35, 37) },
          { size: "30", aliases: ["M"], waist: fromInches(31, 33), hip: fromInches(37, 39) },
          { size: "32", waist: fromInches(33, 35), hip: fromInches(39, 41) },
          { size: "34", aliases: ["L"], waist: fromInches(35, 37), hip: fromInches(41, 43) },
          { size: "36", aliases: ["XL"], waist: fromInches(37, 39), hip: fromInches(43, 45) },
          { size: "38", waist: fromInches(39, 41), hip: fromInches(45, 47) },
          { size: "40", aliases: ["XXL", "2XL"], waist: fromInches(41, 43), hip: fromInches(47, 49) },
        ],
      },
    },
  };

  function normalize(value) {
    return String(value || "").trim().toUpperCase().replace(/[\s_-]+/g, "");
  }

  function detectBrand(modelName) {
    const normalized = String(modelName || "").toLowerCase();
    return BRAND_ORDER.find((brand) => BRAND_ALIASES[brand].some((alias) => normalized.includes(alias))) || "";
  }

  function isRaceModel(modelName) {
    return RACE_MODEL_PATTERN.test(String(modelName || ""));
  }

  function findRow(chart, size) {
    const wanted = normalize(size);
    return chart.rows.find((row) => [row.size].concat(row.aliases || []).some((candidate) => normalize(candidate) === wanted));
  }

  function midpoint(range) {
    return range ? (range[0] + range[1]) / 2 : null;
  }

  function proxyFromCurrent(chart, row, fit) {
    const currentIndex = chart.rows.indexOf(row);
    const shift = fit === "tight" ? 1 : fit === "loose" ? -1 : 0;
    const targetIndex = Math.max(0, Math.min(chart.rows.length - 1, currentIndex + shift));
    const target = chart.rows[targetIndex];
    return {
      chest: midpoint(target.chest),
      bust: midpoint(target.bust),
      waist: midpoint(target.waist),
      hip: midpoint(target.hip),
      torso: midpoint(target.torso),
    };
  }

  function distanceFromRange(value, range, pointValues) {
    if (value == null || !range) return null;
    let low = range[0];
    let high = range[1];
    if (pointValues && low === high) {
      low -= 2.5;
      high += 2.5;
    }
    if (value >= low && value <= high) return 0;
    const width = Math.max(high - low, 4);
    return (value < low ? low - value : value - high) / width;
  }

  function rankRows(chart, measurements) {
    const keys = ["bust", "chest", "waist", "hip", "torso"];
    return chart.rows.map((row, index) => {
      const distances = keys
        .map((key) => distanceFromRange(measurements[key], row[key], chart.pointValues))
        .filter((value) => value != null);
      if (!distances.length) return { row, index, score: Number.POSITIVE_INFINITY };
      const average = distances.reduce((sum, value) => sum + value, 0) / distances.length;
      return { row, index, score: average + Math.max(...distances) * 0.45 };
    }).sort((a, b) => a.score - b.score || a.index - b.index);
  }

  function recommend(profile, measurements) {
    return BRAND_ORDER.map((brand) => {
      const chart = CHARTS[profile][brand];
      const ranked = rankRows(chart, measurements);
      const best = ranked[0];
      const next = ranked[1];
      if (!Number.isFinite(best.score)) {
        return {
          brand,
          name: chart.name,
          size: "추가 치수 필요",
          alternate: "",
          note: chart.note,
          source: chart.source,
          regionCode: chart.regionCode,
          regionLabel: chart.regionLabel,
          labelSystem: chart.labelSystem,
          score: best.score,
          unavailable: true,
        };
      }
      const boundary = next && Math.abs(next.score - best.score) < 0.2;
      return {
        brand,
        name: chart.name,
        size: best.row.size,
        alternate: boundary ? next.row.size : "",
        note: chart.note,
        source: chart.source,
        regionCode: chart.regionCode,
        regionLabel: chart.regionLabel,
        labelSystem: chart.labelSystem,
        score: best.score,
        unavailable: false,
      };
    });
  }

  window.SWIMWEAR_SIZING = {
    BRAND_ORDER,
    CHARTS,
    detectBrand,
    findRow,
    isRaceModel,
    proxyFromCurrent,
    recommend,
  };
})();
