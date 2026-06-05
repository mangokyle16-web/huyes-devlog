/**
 * qs_file_processor: Process a .qs file and output spectral vectors to stdout
 * Usage: qs_file_processor <qsbs_path> <qs_file_path>
 *
 * Output (stdout, binary):
 *   [n_bands: uint32 LE][width: uint32 LE][height: uint32 LE][dtype: uint32 LE=4]
 *   [band_data: float32 × 5 × H × W]  -- NDVI, GNDVI, NDRE, OSAVI, LCI
 */
extern "C" {
#include "qs_camera.h"
#include "qs_fileio.h"
#include "qs_agriculture.h"
}
#include <cstdio>
#include <cstdlib>
#include <vector>

static void write_u32(uint32_t v) { fwrite(&v, 4, 1, stdout); }

int main(int argc, char* argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <qsbs> <qs_file>\n", argv[0]);
        return 1;
    }

    uint8_t* qsbsData = nullptr; size_t qsbsSize = 0;
    if (loadQsbsFile(argv[1], &qsbsData, &qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[ERROR] cannot load %s\n", argv[1]); return 1;
    }

    QsAgricultureContext* agCtx = nullptr;
    if (initQsAgriculture(&agCtx, qsbsData, qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[ERROR] initQsAgriculture\n"); return 1;
    }

    uint8_t* qsData = nullptr; size_t qsSize = 0;
    if (loadQsFile(argv[2], &qsData, &qsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[ERROR] cannot load %s\n", argv[2]); return 1;
    }

    uint8_t* qabData = nullptr; size_t qabSize = 0;
    if (qsToQab(agCtx, qsData, qsSize, &qabData, &qabSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[ERROR] qsToQab\n"); return 1;
    }

    double *ndvi=nullptr,*gndvi=nullptr,*ndre=nullptr,*osavi=nullptr,*lci=nullptr;
    uint32_t W=0,H=0, w2=0,h2=0,w3=0,h3=0,w4=0,h4=0,w5=0,h5=0;
    bool ok = true;
    ok &= (qabToNdvi (qabData,qabSize,&ndvi, &W, &H ) == QS_ERR_SUCCESS);
    ok &= (qabToGndvi(qabData,qabSize,&gndvi,&w2,&h2) == QS_ERR_SUCCESS);
    ok &= (qabToNdre (qabData,qabSize,&ndre, &w3,&h3) == QS_ERR_SUCCESS);
    ok &= (qabToOsavi(qabData,qabSize,&osavi,&w4,&h4) == QS_ERR_SUCCESS);
    ok &= (qabToLci  (qabData,qabSize,&lci,  &w5,&h5) == QS_ERR_SUCCESS);

    if (!ok || W == 0 || H == 0) {
        fprintf(stderr, "[ERROR] index computation failed\n"); return 1;
    }

    const size_t n_px = (size_t)W * H;
    std::vector<float> f32(5 * n_px);
    const double* bands[5] = {ndvi, gndvi, ndre, osavi, lci};
    for (int b = 0; b < 5; ++b)
        for (size_t i = 0; i < n_px; ++i)
            f32[b * n_px + i] = static_cast<float>(bands[b][i]);

    freopen(nullptr, "wb", stdout);
    write_u32(5); write_u32(W); write_u32(H); write_u32(4);
    fwrite(f32.data(), 4, 5 * n_px, stdout);
    fflush(stdout);

    freeQsData(ndvi); freeQsData(gndvi); freeQsData(ndre);
    freeQsData(osavi); freeQsData(lci);
    freeQsData(qabData); freeQsData(qsData); freeQsData(qsbsData);
    deinitQsAgriculture(agCtx);
    fprintf(stderr, "[OK] %s: W=%u H=%u\n", argv[2], W, H);
    return 0;
}
