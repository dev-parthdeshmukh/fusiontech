const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const path = require("path");
const out = path.join(__dirname, "assets", "icons");
const want = {
  money: ["FaMoneyBillWave", "#FF7A3D"], hospital: ["FaHospitalAlt", "#C3C9D4"], clinic: ["FaClinicMedical", "#7DD3FC"],
  users: ["FaUsers", "#FFB547"], brain: ["FaBrain", "#7DD3FC"], radiation: ["FaRadiation", "#FF7A3D"],
  scanner: ["FaXRay", "#C3C9D4"], server: ["FaServer", "#3DDC6A"], target: ["FaBullseye", "#FF6B6B"],
  check: ["FaCheckCircle", "#3DDC6A"], shield: ["FaShieldAlt", "#3DDC6A"], microchip: ["FaMicrochip", "#7DD3FC"],
  rocket: ["FaRocket", "#FF7A3D"], flask: ["FaFlask", "#7DD3FC"], lungs: ["FaLungs", "#FFB547"],
  route: ["FaRoute", "#3DDC6A"], book: ["FaBookMedical", "#7DD3FC"], cogs: ["FaCogs", "#C3C9D4"],
  laptop: ["FaLaptopMedical", "#7DD3FC"], rupee: ["FaRupeeSign", "#3DDC6A"], network: ["FaNetworkWired", "#7DD3FC"],
  vial: ["FaVial", "#FFB547"], eye: ["FaEye", "#FF6B6B"], play: ["FaPlayCircle", "#FF7A3D"], lock: ["FaLock", "#3DDC6A"],
};
(async () => {
  for (const [name, [comp, color]] of Object.entries(want)) {
    const C = fa[comp];
    if (!C) { console.log("missing", comp); continue; }
    const svg = renderToStaticMarkup(React.createElement(C, { size: 512, color }));
    await sharp(Buffer.from(svg)).resize(320, 320).png().toFile(`${out}/${name}.png`);
  }
  console.log("icons done");
})();
