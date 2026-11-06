using Ryujinx.Graphics.Shader.StructuredIr;
using Ryujinx.Graphics.Shader.Translation;

namespace Ryujinx.Graphics.Shader.CodeGen
{
    readonly struct CodeGenParameters
    {
        public readonly AttributeUsage AttributeUsage;
        public readonly ShaderDefinitions Definitions;
        public readonly ShaderProperties Properties;
        public readonly HostCapabilities HostCapabilities;
        public readonly ILogger Logger;
        public readonly TargetApi TargetApi;
        // nxnative: TranslationOptions.LoopIterationCap (0 = no limit)
        public readonly uint LoopIterationCap;

        public CodeGenParameters(
            AttributeUsage attributeUsage,
            ShaderDefinitions definitions,
            ShaderProperties properties,
            HostCapabilities hostCapabilities,
            ILogger logger,
            TargetApi targetApi,
            uint loopIterationCap = 0)
        {
            AttributeUsage = attributeUsage;
            Definitions = definitions;
            Properties = properties;
            HostCapabilities = hostCapabilities;
            Logger = logger;
            TargetApi = targetApi;
            LoopIterationCap = loopIterationCap;
        }
    }
}
