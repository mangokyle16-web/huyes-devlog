#ifndef QS_AGRICULTURE_H
#define QS_AGRICULTURE_H

/**
 * @file qs_agriculture.h
 * @brief QS农业动态链接库头文件。
 *
 * This header file uses utf-8 encoding for comments.
 * 所有的中文注释都使用utf-8编码。
 */

#include "qs_errorcodes.h"

#include <stdint.h>
#include <stddef.h>


#define API_PUBLIC __attribute((visibility("default")))
#ifdef __cplusplus
extern "C" {
#endif
	/**
	 * @brief 农业上下文，用于管理资源。
	 */
	typedef struct QsAgricultureContextTag QsAgricultureContext;
	/**
	 * @brief 初始化上下文。
	 * @param context 光谱反演上下文，需要传入nullptr，在函数中申请内存，由deinitQsSpecinv释放。
	 * @param qsbsData 通过loadQsbsFile读取的qsbs文件数据指针。
	 * @param qsbsSize qsbs文件数据大小。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes initQsAgriculture(QsAgricultureContext** context, const uint8_t* qsbsData, const size_t qsbsSize);
	/**
	 * @brief 农业上下文资源释放函数。
	 * @param context 农业上下文。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes deinitQsAgriculture(QsAgricultureContext* context);
	/**
	 * @brief qs计算农业波段图，434nm-466nm,544nm-576nm,634nm-666nm,714nm-746nm,814nm-866nm。
	 * @param context 农业上下文。
	 * @param qsData 通过loadQsFile读取的qs文件数据指针。
	 * @param qsSize qs文件数据大小。
	 * @param qabData 计算结果的波段图像数据，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param qabDataSize 波段图像数据大小。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qsToQab(
		QsAgricultureContext* context, const uint8_t* qsData, const size_t qsSize,
		uint8_t** qabData, size_t* qabDataSize);
	/**
	 * @brief qab文件转灰度图像。
	 * @param context 图像处理上下文。
	 * @param qabData 通过loadQabFile读取的qab文件数据指针。
	 * @param qabSize qab文件数据大小。
	 * @param ratio 灰度图像的亮度倍率，当结果过亮或过暗时，可通过该参数调整。
	 * @param grayData 灰度图像数据指针，维度[5][height][width]，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param width 灰度图像的宽。
	 * @param height 灰度图像的高。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qabToGray(
		const uint8_t* qabData, const size_t qabSize, const double ratio,
		double** grayData, int* width, int* height);
	/**
	 * @brief 读取qab(农业五波段图像文件)。
	 * @param path qab文件路径。
	 * @param data 文件数据指针，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param size 返回文件数据长度。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes loadQabFile(const char* path, uint8_t** data, size_t* size);
	/**
	 * @brief 保存qab(农业五波段图像文件)。
	 * @param path qab文件路径。
	 * @param data 文件数据指针。
	 * @param size 文件数据长度。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes saveQabFile(const char* path, const uint8_t* data, const size_t size);
	/**
	 * @brief qab文件转ndvi。
	 * @param qabData 通过loadQabFile读取的qab文件数据指针。
	 * @param qabSize qab文件数据大小。
	 * @param ndvi ndvi数据指针，维度[height][width]，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param width 灰度图像的宽。
	 * @param height 灰度图像的高。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qabToNdvi(
		const uint8_t* qabData, const size_t qabSize, 
		double** ndvi, uint32_t* width, uint32_t* height);
	/**
	 * @brief qab文件转gndvi。
	 * @param qabData 通过loadQabFile读取的qab文件数据指针。
	 * @param qabSize qab文件数据大小。
	 * @param gndvi gndvi数据指针，维度[height][width]，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param width 灰度图像的宽。
	 * @param height 灰度图像的高。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qabToGndvi(
		const uint8_t* qabData, const size_t qabSize,
		double** gndvi, uint32_t* width, uint32_t* height);
	/**
	 * @brief qab文件转ndre。
	 * @param qabData 通过loadQabFile读取的qab文件数据指针。
	 * @param qabSize qab文件数据大小。
	 * @param ndre ndre数据指针，维度[height][width]，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param width 灰度图像的宽。
	 * @param height 灰度图像的高。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qabToNdre(
		const uint8_t* qabData, const size_t qabSize,
		double** ndre, uint32_t* width, uint32_t* height);
	/**
	 * @brief qab文件转osavi。
	 * @param qabData 通过loadQabFile读取的qab文件数据指针。
	 * @param qabSize qab文件数据大小。
	 * @param osavi osavi数据指针，维度[height][width]，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param width 灰度图像的宽。
	 * @param height 灰度图像的高。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qabToOsavi(
		const uint8_t* qabData, const size_t qabSize,
		double** osavi, uint32_t* width, uint32_t* height);
	/**
	 * @brief qab文件转lci。
	 * @param qabData 通过loadQabFile读取的qab文件数据指针。
	 * @param qabSize qab文件数据大小。
	 * @param lci lci数据指针，维度[height][width]，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param width 灰度图像的宽。
	 * @param height 灰度图像的高。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qabToLci(
		const uint8_t* qabData, const size_t qabSize,
		double** lci, uint32_t* width, uint32_t* height);
	/**
	 * @brief 植被指数转伪彩图像。
	 * @param vegetationIndex 植被指数数据指针。
	 * @param width 图像的宽。
	 * @param height 图像的高。
	 * @param rgbData 彩色图像数据指针，在外部申请内存，需要传入非nullptr。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes vegetationIndexToPseudoColor(
		const double* vegetationIndex,const uint32_t width,const uint32_t height,
		uint8_t* rgbData);

#ifdef __cplusplus
}
#endif

#endif
