#ifndef QS_SPECINV_H
#define QS_SPECINV_H

/**
 * @file qs_specinv.h
 * @brief QS光谱反演动态链接库头文件。
 *
 * This header file uses utf-8 encoding for comments.
 * 所有的中文注释都使用utf-8编码。
 */

#include "qs_errorcodes.h"

#include <stdint.h>

#include <stdint.h>
#include <stddef.h>
#define API_PUBLIC __attribute((visibility("default")))

#ifdef __cplusplus
extern "C" {
#endif
	/**
	 * @brief 光谱反演上下文，用于管理资源。
	 */
	typedef struct QsSpecinvContextTag QsSpecinvContext;
	/**
	 * @brief 初始化上下文。
	 * @param context 光谱反演上下文，需要传入nullptr，在函数中申请内存，由deinitQsSpecinv释放。
	 * @param qsbsData 通过loadQsbsFile读取的qsbs文件数据指针。
	 * @param qsbsSize qsbs文件数据大小。
	 * @param qsdbPath qsdb文件路径。
	 * @param begin 光谱范围起始波长。
	 * @param end 光谱范围终止波长。
	 * @param lightSourceList 光源列表，需要传入nullptr，在函数中指向字符串数组，字符串数组内存由上下文管理。
	 * @param lightSourceSize 光源数量。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes initQsSpecinv(
		QsSpecinvContext** context, const uint8_t* qsbsData, const size_t qsbsSize, const char* qsdbPath,
		size_t* begin, size_t* end, char*** lightSourceList, size_t* lightSourceSize);
	/**
	 * @brief 光谱反演上下文资源释放函数。
	 * @param context 光谱反演上下文。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes deinitQsSpecinv(QsSpecinvContext* context);
	/**
	 * @brief 计算光谱曲线函数。
	 * @param context 光谱反演上下文。
	 * @param qsData 通过loadQsFile读取的qs文件数据指针。
	 * @param qsSize qs文件数据大小。
	 * @param lightSource 光源列表索引，当传入-1时，自动识别图像光源。
	 * @param isMask 是否使用掩膜作为计算区域。
	 * @param rect 当isMask为false时，通过该参数传入区域坐标，另一项传nullptr，int[y1,y2,x1,x2]。
	 * @param mask 当isMask为true时，通过该参数传入掩膜，另一项传nullptr，掩膜中true参与运算，掩膜分辨率与图像一致。
	 * @param curveData 计算结果的光谱曲线，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param curveDataSize 光谱曲线数组大小。
	 * @param info 光谱曲线文件信息，n行格式为<tag>value\n，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param infoSize 光谱曲线文件信息大小。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qsToQsc(
		QsSpecinvContext* context, const uint8_t* qsData, const size_t qsSize, const int lightSource,
		const bool isMask, const int* rect, const bool* mask,
		double** curveData, size_t* curveDataSize, char** info, size_t* infoSize);
	/**
	 * @brief 读取qsc(光谱曲线文件)。
	 * @param path qsc文件路径。
	 * @param info 文件信息指针，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param infoSize 文件信息长度。
	 * @param data 文件数据，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param dataSize 文件数据长度。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes loadQscFile(
		const char* path, char** info, size_t* infoSize,
		double** data, size_t* size);
	/**
	 * @brief 保存qsc(光谱曲线文件)，qsc文件可通过记事本打开。
	 * @param path qsc文件路径。
	 * @param info 文件信息指针。
	 * @param infoSize 文件信息长度。
	 * @param data 文件数据。
	 * @param dataSize 文件数据长度。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes saveQscFile(
		const char* path, const char* info, const size_t infoSize,
		const double* data, const size_t size);
	/**
	 * @brief 计算波段图像函数。
	 * @param context 光谱反演上下文。
	 * @param qsData 通过loadQsFile读取的qs文件数据指针。
	 * @param qsSize qs文件数据大小。
	 * @param lightSource 光源列表索引，当传入-1时，自动识别图像光源。
	 * @param intricacy 计算精细度，范围[1,1000]，该值越大，计算速度越慢，结果越准确。
	 * @param bandRange 波段范围，bandSize*{起始波长,终止波长}，输入的范围应符合相机的光谱分辨率,例:350-950范围20nm分辨率，{350,370}、{350,390}合法，{360,380}非法。
	 * @param bandNum 波段数量。
	 * @param qsiData 计算结果的光谱图像数据，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param qsiDataSize 光谱图像数据大小。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qsToQsi(
		QsSpecinvContext* context, const uint8_t* qsData, const size_t qsSize, const int lightSource,
		const int intricacy, const int(*bandRange)[2], const int bandNum,
		uint8_t** qsiData, size_t* qsiDataSize);
	/**
	 * @brief qsi文件转灰度图像。
	 * @param context 图像处理上下文。
	 * @param qsiData 通过loadQsiFile读取的qsi文件数据指针。
	 * @param qsiSize qsi文件数据大小。
	 * @param ratio 灰度图像的亮度倍率，当结果过亮或过暗时，可通过该参数调整。
	 * @param grayData 灰度图像数据指针，维度[bandSize][height][width]，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param width 灰度图像的宽。
	 * @param height 灰度图像的高。
	 * @param bandRange 波段范围，bandSize*{起始波长,终止波长}，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param bandNum 波段数量。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes qsiToGray(
		const uint8_t* qsiData, const size_t qsiSize, const double ratio,
		double** grayData, int* width, int* height,
		int(**bandRange)[2], int* bandNum);
	/**
	 * @brief 读取qsi(波段图像文件)。
	 * @param path qsi文件路径。
	 * @param data 文件数据指针，需要传入nullptr，在函数中申请内存，并在外部释放。
	 * @param size 返回文件数据长度。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes loadQsiFile(const char* path, uint8_t** data, size_t* size);
	/**
	 * @brief 保存qsi(波段图像文件)。
	 * @param path qsi文件路径。
	 * @param data 文件数据指针。
	 * @param size 文件数据长度。
	 * @return 返回QsErrorcodes错误代码。
	 */
	API_PUBLIC QsErrorcodes saveQsiFile(const char* path, const uint8_t* data, const size_t size);

#ifdef __cplusplus
}
#endif

#endif
